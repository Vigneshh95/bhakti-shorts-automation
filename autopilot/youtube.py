"""Scheduled YouTube upload with SEO-ready metadata. Reuses the channel's existing OAuth
client + token (paths in config.ini), so no new sign-in is needed if the uploader already works."""
from __future__ import annotations

import configparser
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from autopilot.script import Script
from shorts.config import ROOT
from shorts.log import log

SCOPES = ["https://www.googleapis.com/auth/youtube"]
# India has no daylight saving, so a fixed offset is exact (and zoneinfo has no timezone
# database on Windows without the extra tzdata package).
IST = timezone(timedelta(hours=5, minutes=30), "IST")


class SignInRequired(RuntimeError):
    pass


def channel_config() -> dict:
    cp = configparser.ConfigParser()
    cp.read(ROOT / "config.ini", encoding="utf-8")
    resolve = lambda v: Path(v) if Path(v).is_absolute() else ROOT / v  # noqa: E731
    import os

    # config.ini names this laptop's files; another machine (the cloud runner) points to its own
    return {
        "client_secrets": resolve(os.environ.get("YT_CLIENT_SECRET_FILE") or cp.get("Paths", "client_secrets")),
        "token_file": resolve(os.environ.get("YT_TOKEN_FILE") or cp.get("Paths", "token_file")),
        "playlist_id": cp.get("YouTube", "playlist_id", fallback=""),
        "instagram_url": cp.get("Social", "instagram_url", fallback=""),
        "support_url": cp.get("Social", "support_url", fallback=""),
    }


def publish_time(now: datetime, settings: dict) -> datetime:
    """Next configured IST slot at least min_lead_minutes away, as an aware UTC datetime."""
    hh, mm = map(int, settings["youtube"]["publish_time"].split(":"))
    local_now = now.astimezone(IST)
    slot = datetime.combine(local_now.date(), time(hh, mm), IST)
    if slot - local_now < timedelta(minutes=settings["youtube"]["min_lead_minutes"]):
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


def _picture_credit(image_id: str, settings: dict | None) -> str:
    """The credit line for today's picture, if <image_folder>/credits.json lists one."""
    folder = (settings or {}).get("paths", {}).get("image_folder")
    if not folder or not (folder / "credits.json").exists():
        return ""
    try:
        return str(json.loads((folder / "credits.json").read_text(encoding="utf-8")).get(image_id, ""))
    except ValueError:
        return ""


def build_description(script: Script, channel: dict, settings: dict | None = None) -> str:
    yt = (settings or {}).get("youtube", {})
    parts = [script.youtube_description, "", "\n".join(script.lines), ""]
    if script.source:  # a retold text: credit it, and say plainly how the Short was made
        parts += [f"ஆதாரம் (Source): {script.source['credit']}", script.source["url"]]
        if yt.get("source_note"):
            parts.append(yt["source_note"])
        parts.append("")
    credit = _picture_credit(script.image_id, settings)
    if credit:  # a picture whose licence asks for attribution (credits.json in the picture folder)
        parts += [credit, ""]
    parts.append(yt.get("footer") or "🙏 தினமும் முருகன் அருள் வாக்கு — Subscribe செய்து பகிருங்கள்.")
    if channel["instagram_url"]:
        parts.append(f"Instagram: {channel['instagram_url']}")
    if channel["support_url"]:
        parts.append(f"Channel: {channel['support_url']}")
    hashtags = list(dict.fromkeys(script.hashtags + ["#Shorts"]))  # #Shorts last, no duplicates
    parts += ["", " ".join(hashtags)]
    return "\n".join(parts)[:4900]  # YouTube's limit is 5000


def _credentials(channel: dict, interactive: bool):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if channel["token_file"].exists():
        creds = Credentials.from_authorized_user_file(str(channel["token_file"]), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            channel["token_file"].write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 -- google raises several types here
            log.warning("  YouTube token refresh failed: %s", e)
            creds = None
    if creds and creds.valid:
        return creds
    if not interactive:
        raise SignInRequired("YouTube sign-in has expired. Double-click auto_short.bat once to sign in again "
                             "(the scheduled run can't open a browser).")
    from google_auth_oauthlib.flow import InstalledAppFlow

    log.info("  opening the browser for YouTube sign-in…")
    flow = InstalledAppFlow.from_client_secrets_file(str(channel["client_secrets"]), SCOPES)
    creds = flow.run_local_server(port=0)
    channel["token_file"].write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload(video: Path, script: Script, settings: dict, publish_at: datetime | None, interactive: bool) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    channel = channel_config()
    yt = build("youtube", "v3", credentials=_credentials(channel, interactive), cache_discovery=False)
    status = {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(settings["youtube"]["disclose_ai"])}
    if publish_at:
        status.update(privacyStatus="private", publishAt=publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    else:
        status["privacyStatus"] = "public"
    body = {
        "snippet": {
            "title": script.youtube_title,
            "description": build_description(script, channel, settings),
            "tags": script.tags,
            "categoryId": settings["youtube"]["category_id"],
            "defaultLanguage": settings["youtube"]["language"],
            "defaultAudioLanguage": settings["youtube"]["language"],
        },
        "status": status,
    }
    request = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            log.info("  uploading %d%%", int(progress.progress() * 100))
    video_id = response["id"]

    playlist = _series_playlist(yt, settings) or channel["playlist_id"]  # a series can have its own
    if settings["youtube"]["playlist"] and playlist:
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": playlist, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
        except Exception as e:  # noqa: BLE001 -- the upload itself succeeded; don't fail the run over the playlist
            log.warning("  couldn't add to playlist: %s", e)
    return video_id


def _series_playlist(yt, settings: dict) -> str:
    """The series' own playlist: [youtube] playlist_id, else the one named playlist_title on the
    channel, created (public) the first time. Remembered next to the series' history."""
    y = settings["youtube"]
    if y.get("playlist_id") or not y.get("playlist_title"):
        return y.get("playlist_id", "")
    memo = settings["paths"]["state"].with_name("playlist.json")
    if memo.exists():
        return json.loads(memo.read_text(encoding="utf-8"))["id"]
    try:
        found, page = "", None
        while not found:
            res = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
            found = next((p["id"] for p in res.get("items", []) if p["snippet"]["title"] == y["playlist_title"]), "")
            page = res.get("nextPageToken")
            if not page:
                break
        if not found:
            found = yt.playlists().insert(part="snippet,status", body={
                "snippet": {"title": y["playlist_title"], "defaultLanguage": y["language"],
                            "description": y.get("footer", "")},
                "status": {"privacyStatus": "public"}}).execute()["id"]
            log.info("  created the playlist '%s'", y["playlist_title"])
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.write_text(json.dumps({"id": found, "title": y["playlist_title"]}, ensure_ascii=False), encoding="utf-8")
        return found
    except Exception as e:  # noqa: BLE001 -- never fail an upload over the playlist
        log.warning("  couldn't find or create the playlist: %s", e)
        return ""


def preflight(interactive: bool) -> bool:
    """Checks (and if needed renews) the YouTube sign-in BEFORE the run does any work.
    Interactive: opens the browser for approval right away. Unattended: returns False instead,
    so the run can still make the video and upload it after the user approves."""
    try:
        _credentials(channel_config(), interactive)
        return True
    except SignInRequired:
        return False


def check_sign_in() -> str:
    """Read-only: confirms the saved token works and returns the channel name."""
    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=_credentials(channel_config(), interactive=False), cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return items[0]["snippet"]["title"] if items else "(no channel on this account)"
