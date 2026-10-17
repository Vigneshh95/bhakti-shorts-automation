"""The story pipeline: one command that takes a series from "nothing" to "scheduled on YouTube".

  python -m stories run --series adults       continue the story in progress, or start the next one
  python -m stories run --series kids --no-upload
  python -m stories approve --series adults   you watched the finished story and are happy: upload it
  python -m stories status                    what is made, scheduled and waiting
  python -m stories signin --series kids      sign in to that series' YouTube channel (opens the browser)

A story is made in steps that can each stop and be picked up on the next run (the free speech
models allow a limited number of lines a day; pictures take over an hour on Kaggle):
  write the script -> paint and check the pictures -> act the voices -> render -> thumbnail
  -> YOU WATCH IT AND APPROVE ([pipeline] review_first) -> upload into the next release slot
`run` does as many steps as it can today. It starts a NEW story only when the series has fewer than
[pipeline] stories_ahead stories waiting to go public, so there is always one ready for the next
release slot (stories.toml: [youtube.<series>] days + time) and never a pile of them."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from shorts.log import log, setup_logging
from stories import publish as P
from stories import writer


def episodes(settings: dict, series: str) -> list[Path]:
    """The series' pipeline stories, oldest first (samples and pilots are not part of it)."""
    return sorted(p for p in settings["paths"]["episodes"].glob(f"{series}-*") if p.is_dir())


def _records(settings: dict, series: str) -> list[dict]:
    out = []
    for folder in episodes(settings, series):
        script, published = folder / "script.json", folder / "published.json"
        out.append({"folder": folder,
                    "script": json.loads(script.read_text(encoding="utf-8")) if script.exists() else None,
                    "published": json.loads(published.read_text(encoding="utf-8")) if published.exists() else None,
                    "video": (folder / "video.mp4").exists()})
    return out


def _next_topic(settings: dict, series: str, records: list[dict]) -> str:
    """The first topic of the list not told yet; when all are told, the one told longest ago."""
    topics = settings["topics"][series]
    used = [r["script"]["topic"] for r in records if r["script"] and r["script"].get("topic")]
    fresh = [t for t in topics if t not in used]
    if fresh:
        return fresh[0]
    return min(topics, key=lambda t: max(i for i, u in enumerate(used) if u == t))


def run(series: str, upload: bool = True, interactive: bool = True) -> str:
    """Does today's share of the work for the series. Returns one line saying where it stands."""
    from stories import make
    from stories.voice import VoiceLimit

    from autopilot import sync

    settings = writer.load_settings()
    sync.pull()   # the shared record: what the laptop or the cloud has already written and scheduled
    try:
        return _run(series, upload, interactive, settings, make, VoiceLimit)
    finally:
        sync.push(pictures=False)


def _here() -> str:
    import os

    return "cloud" if os.environ.get("GITHUB_ACTIONS") else "laptop"


def _maker(folder: Path) -> str | None:
    try:
        return json.loads((folder / "maker.json").read_text(encoding="utf-8")).get("where")
    except (OSError, ValueError):
        return None


def _run(series: str, upload: bool, interactive: bool, settings: dict, make, VoiceLimit) -> str:
    records = _records(settings, series)
    open_ones = [r for r in records if not r["published"]]
    mine = [r for r in open_ones if _maker(r["folder"]) in (None, _here())]
    if open_ones and not mine:
        # being made on the other machine (its pictures and voice lines are there): leave it alone,
        # and don't start another story of this series beside it
        other = open_ones[0]["folder"]
        return f"{series}: {other.name} is being made on the {_maker(other)}; nothing to do here"
    if mine:
        current = mine[0]
        folder = current["folder"]
    else:
        waiting = [r for r in records if r["published"] and datetime.fromisoformat(r["published"]["slot"]) > datetime.now(P.IST)]
        ahead = int(settings.get("pipeline", {}).get("stories_ahead", 2))
        if len(waiting) >= ahead:
            return f"{series}: {len(waiting)} stories are already scheduled; nothing to make today"
        folder = settings["paths"]["episodes"] / f"{series}-{datetime.now(P.IST):%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)
        current = {"folder": folder, "script": None, "video": False}

    if not (folder / "maker.json").exists():
        (folder / "maker.json").write_text(json.dumps({"where": _here()}), encoding="utf-8")
    if not (folder / "script.json").exists():
        topic = _next_topic(settings, series, records)
        log.info("▶ writing a new %s story: %s", series, topic)
        titles = [r["script"]["title_ta"] for r in records if r["script"]]
        script = writer.write(series, topic, settings, titles)
        (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("  \"%s\" (%d scenes)", script["title_ta"], len(script["scenes"]))

    _apply_rework(folder)
    if not (folder / "made.json").exists():      # (a finished story is not rendered again on every run)
        try:
            log.info("▶ pictures, voices and video for %s", folder.name)
            make.make(folder, settings)
        except VoiceLimit as e:
            return f"{series}: {folder.name} is waiting for tomorrow's free voice lines ({e})"
        (folder / "made.json").write_text(json.dumps({"made_at": datetime.now(P.IST).isoformat()}), encoding="utf-8")

    if not upload:
        return f"{series}: {folder.name} is made ({folder / 'video.mp4'}); not uploaded"
    if settings.get("pipeline", {}).get("review_first", True) and not (folder / "approved.json").exists():
        # Watch first: nothing goes to YouTube until you have seen it and approved it.
        if interactive:
            _open(folder / "video.mp4")
            _open(folder / "thumbnail.jpg")
        return (f"{series}: {folder.name} is made and waiting for your approval. Watch {folder / 'video.mp4'} "
                f"and, if you are happy, run story_approve_{series}.bat to schedule it on YouTube")
    record = P.publish(folder, settings, interactive)
    if record is None:
        return f"{series}: {folder.name} is made, but this series' YouTube channel is not signed in yet"
    return (f"{series}: {folder.name} uploaded https://youtu.be/{record['video_id']} -- public "
            f"{datetime.fromisoformat(record['slot']):%a %d %b %H:%M} IST")


def _rework_pending(folder: Path) -> bool:
    """A rework was asked for and the story has not been finished again since."""
    try:
        rid = json.loads((folder / "rework.json").read_text(encoding="utf-8"))["id"]
    except (OSError, ValueError, KeyError):
        return False
    try:
        made = json.loads((folder / "made.json").read_text(encoding="utf-8")).get("made_at", "")
    except (OSError, ValueError):
        return True
    made_id = made[:19].replace("-", "").replace(":", "").replace("T", "")
    return not made_id or made_id < rid


def _apply_rework(folder: Path) -> None:
    """A finished story sent back (rework.json, from `python -m stories rework` on any machine):
    the named pictures are repainted with their fix notes, every picture is checked again, every
    voice line is heard again, and the story waits for approval again."""
    req = folder / "rework.json"
    if not req.exists():
        return
    request = json.loads(req.read_text(encoding="utf-8"))
    done_path = folder / "rework_done.json"
    done = json.loads(done_path.read_text(encoding="utf-8")) if done_path.exists() else []
    if request["id"] in done:
        return
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    for n, fix in request.get("scenes", {}).items():
        script["scenes"][int(n) - 1]["fix"] = fix
        (folder / "pictures" / f"scene_{int(n):02d}.png").unlink(missing_ok=True)
    (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    for marker in [*(folder / "pictures").glob(".checked_*"), folder / "made.json", folder / "approved.json"]:
        marker.unlink(missing_ok=True)
    for heard in Path(".cache/story_actor").glob("*.heard"):     # every line is heard again
        heard.unlink()
    done.append(request["id"])
    done_path.write_text(json.dumps(done), encoding="utf-8")
    log.info("▶ reworking %s: %s", folder.name, request.get("why", ""))


def rework(series: str, scenes: dict[int, str], why: str) -> str:
    """Sends the series' finished (not yet uploaded) story back: pictures to repaint with what they
    should show, and every voice line to be heard again. The machine making it does the work."""
    from autopilot import sync

    settings = writer.load_settings()
    sync.pull()
    try:
        ready = [r for r in _records(settings, series) if not r["published"]]
        if not ready:
            return f"{series}: no unpublished story to rework"
        folder = ready[0]["folder"]
        rid = datetime.now(P.IST).strftime("%Y%m%d%H%M%S")
        (folder / "rework.json").write_text(json.dumps({"id": rid, "why": why, "scenes": {str(k): v for k, v in scenes.items()}},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
        (folder / "approved.json").unlink(missing_ok=True)
        if _maker(folder) in (None, _here()):
            _apply_rework(folder)
        return f"{series}: {folder.name} sent back for rework ({why}); it waits for your approval again when done"
    finally:
        sync.push(pictures=False)


def _open(path: Path) -> None:
    import os

    if path.exists() and hasattr(os, "startfile"):
        try:
            os.startfile(path)  # noqa: S606 -- the user's own video, in their own player
        except OSError:
            pass


def approve(series: str, interactive: bool = True) -> str:
    """Marks the series' finished, unapproved story as approved and uploads it into the next slot."""
    from autopilot import sync

    settings = writer.load_settings()
    sync.pull()
    try:
        ready = [r for r in _records(settings, series) if not r["published"] and (r["folder"] / "made.json").exists()]
        if not ready:
            return f"{series}: no finished story is waiting for approval"
        folder = ready[0]["folder"]
        if _rework_pending(folder):
            return f"{series}: {folder.name} is still being reworked; approve it when the new version is ready"
        (folder / "approved.json").write_text(json.dumps({"approved_at": datetime.now(P.IST).isoformat()}), encoding="utf-8")
        if _maker(folder) not in (None, _here()):
            # made on the other machine: its video is there, so it uploads it on its next run
            return (f"{series}: {folder.name} is approved; the {_maker(folder)} has its video and will schedule it on "
                    f"its next run (the cloud's story runs start about 1 AM and 7 AM)")
        record = P.publish(folder, settings, interactive)
        if record is None:
            return f"{series}: {folder.name} is approved, but this series' YouTube channel is not signed in yet"
        return (f"{series}: {folder.name} uploaded https://youtu.be/{record['video_id']} -- public "
                f"{datetime.fromisoformat(record['slot']):%a %d %b %H:%M} IST (private until then)")
    finally:
        sync.push(pictures=False)


def status() -> list[str]:
    settings, lines = writer.load_settings(), []
    for series in ("adults", "kids"):
        for r in _records(settings, series):
            title = r["script"]["title_ta"] if r["script"] else "(not written yet)"
            if r["published"]:
                state = f"scheduled {datetime.fromisoformat(r['published']['slot']):%a %d %b %H:%M}  https://youtu.be/{r['published']['video_id']}"
            else:
                made, ok = (r["folder"] / "made.json").exists(), (r["folder"] / "approved.json").exists()
                where = f" (on the {_maker(r['folder'])})" if _maker(r["folder"]) else ""
                state = ("approved, uploads on the next run" if made and ok else
                         "MADE: waiting for your approval" if made else f"in progress{where}")
            lines.append(f"{series:7} {r['folder'].name:22} {title}  --  {state}")
    return lines or ["no pipeline stories yet"]


def main(argv: list[str] | None = None) -> int:
    setup_logging(False)
    ap = argparse.ArgumentParser(prog="python -m stories", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--series", choices=["adults", "kids"], required=True)
    r.add_argument("--no-upload", action="store_true")
    r.add_argument("--scheduled", action="store_true", help="unattended: never open a browser")
    sub.add_parser("status")
    ok = sub.add_parser("approve")
    ok.add_argument("--series", choices=["adults", "kids"], required=True)
    rw = sub.add_parser("rework", help="send a finished story back: repaint pictures, hear every voice line again")
    rw.add_argument("--series", choices=["adults", "kids"], required=True)
    rw.add_argument("--scene", action="append", default=[], help='N=what the picture should show (repeatable)')
    rw.add_argument("--why", default="changes after review")
    s = sub.add_parser("signin")
    s.add_argument("--series", choices=["adults", "kids"], required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "run":
            log.info("✅ %s", run(args.series, upload=not args.no_upload, interactive=not args.scheduled))
        elif args.cmd == "rework":
            scenes = {int(x.split("=", 1)[0]): x.split("=", 1)[1] for x in args.scene}
            log.info("✅ %s", rework(args.series, scenes, args.why))
        elif args.cmd == "approve":
            log.info("✅ %s", approve(args.series))
        elif args.cmd == "status":
            for line in status():
                log.info("%s", line)
        elif args.cmd == "signin":
            log.info("✅ %s", P.sign_in(args.series, writer.load_settings()))
    except Exception as exc:  # noqa: BLE001 -- one readable line for the console and the log
        log.error("The story pipeline stopped: %s", re.sub(r"\s+", " ", str(exc))[:600])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
