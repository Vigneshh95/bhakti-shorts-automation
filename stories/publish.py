"""Uploads a finished story to YouTube, scheduled for the series' next release slot, with its
thumbnail, playlist, the made-for-kids declaration and the AI-voice disclosure.

Release slots are in stories.toml ([youtube.<series>] days + time, India time): two a week."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autopilot import youtube as Y
from shorts.log import log

IST = timezone(timedelta(hours=5, minutes=30))
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def next_slot(series_cfg: dict, taken: list[str], now: datetime | None = None) -> datetime:
    """The next release time (India time) at least 3 hours away that no story already holds."""
    now = now or datetime.now(IST)
    hour, minute = (int(x) for x in series_cfg["time"].split(":"))
    wanted = {DAYS.index(d) for d in series_cfg["days"]}
    day = now.date()
    for _ in range(60):
        slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
        if day.weekday() in wanted and slot - now >= timedelta(hours=3) and slot.isoformat() not in taken:
            return slot
        day += timedelta(days=1)
    raise RuntimeError("no free release slot in the next 60 days")


def channel(series: str, cfg: dict) -> dict:
    """Where this series uploads: the main channel (config.ini), or the series' own channel when
    [youtube.<series>] token_file names its sign-in file. On the cloud machine the file's place
    comes from YT_TOKEN_FILE_<SERIES>."""
    import os

    from shorts.config import ROOT

    ch = dict(Y.channel_config())
    if cfg.get("token_file"):
        ch["token_file"] = Path(os.environ.get(f"YT_TOKEN_FILE_{series.upper()}") or ROOT / cfg["token_file"])
    return ch


def sign_in(series: str, settings: dict) -> str:
    """Opens the browser to sign in to the series' channel and saves its sign-in file."""
    from googleapiclient.discovery import build

    ch = channel(series, settings["youtube"][series])
    ch["token_file"].unlink(missing_ok=True) if ch["token_file"].name != Y.channel_config()["token_file"].name else None
    yt = build("youtube", "v3", credentials=Y._credentials(ch, True), cache_discovery=False)
    me = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    return f"signed in to the channel \"{me['snippet']['title']}\" for the {series} stories ({ch['token_file'].name})"


def description(script: dict, footer: str) -> str:
    parts = [script["youtube_description"], "",
             f"{script['source_name_ta']}: \"{script['source_line_ta']}\" — {script['source_meaning_ta']}", "",
             f"இன்று செய்து பாருங்கள்: {script['action_ta']}", f"சிந்திக்க: {script['question_ta']}", "",
             "இந்தக் கதையின் படங்களும் குரல்களும் AI உதவியுடன் உருவாக்கப்பட்டவை. "
             "The pictures and voices in this story were made with AI.", "", footer, "",
             " ".join(dict.fromkeys(script.get("hashtags", [])))]
    return "\n".join(parts)[:4900]


def publish(folder: Path, settings: dict, interactive: bool = True) -> dict | None:
    """Uploads <folder>/video.mp4. Returns the record also saved as <folder>/published.json; a
    story that already has that file is not uploaded again. None = the series has its own channel
    and nobody has signed in to it yet (the story stays made and is uploaded on a later run)."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    record_path = folder / "published.json"
    if record_path.exists():
        return json.loads(record_path.read_text(encoding="utf-8"))
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    series = script["series"]
    cfg = settings["youtube"][series]
    ch = channel(series, cfg)
    if cfg.get("token_file") and not ch["token_file"].exists():
        log.warning("  the %s stories have their own YouTube channel, and it is not signed in yet (%s is missing)",
                    series, ch["token_file"].name)
        return None
    taken = [json.loads(p.read_text(encoding="utf-8")).get("slot", "") for p in folder.parent.glob(f"{series}-*/published.json")]
    slot = next_slot(cfg, taken)
    yt = build("youtube", "v3", credentials=Y._credentials(ch, interactive), cache_discovery=False)
    body = {"snippet": {"title": script["youtube_title"][:100], "description": description(script, cfg.get("footer", "")),
                        "tags": script.get("tags", [])[:30], "categoryId": "22", "defaultLanguage": "ta",
                        "defaultAudioLanguage": "ta"},
            "status": {"privacyStatus": "private", "publishAt": slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "selfDeclaredMadeForKids": bool(cfg["made_for_kids"]), "containsSyntheticMedia": True}}
    request = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(folder / "video.mp4"), chunksize=8 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            log.info("  uploading %d%%", int(progress.progress() * 100))
    video_id = response["id"]
    record = {"video_id": video_id, "slot": slot.isoformat(), "title": script["youtube_title"], "thumbnail": False, "playlist": False}
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")   # saved first: never uploaded twice
    thumb = folder / "thumbnail.jpg"
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
            record["thumbnail"] = True
        except Exception as e:  # noqa: BLE001 -- the video is up; the picture can be set by hand in Studio
            log.warning("  the thumbnail was not set (%s): set %s in YouTube Studio", str(e)[:120], thumb)
    if cfg.get("playlist_id"):
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": cfg["playlist_id"], "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            record["playlist"] = True
        except Exception as e:  # noqa: BLE001
            log.warning("  couldn't add to the playlist: %s", str(e)[:120])
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("✅ uploaded https://youtu.be/%s -- goes public %s", video_id, slot.strftime("%a %d %b, %H:%M IST"))
    return record
