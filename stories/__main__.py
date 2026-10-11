"""The story pipeline: one command that takes a series from "nothing" to "scheduled on YouTube".

  python -m stories run --series adults       continue the story in progress, or start the next one
  python -m stories run --series kids --no-upload
  python -m stories status                    what is made, scheduled and waiting
  python -m stories signin --series kids      sign in to that series' YouTube channel (opens the browser)

A story is made in steps that can each stop and be picked up on the next run (the free speech
models allow a limited number of lines a day; pictures take over an hour on Kaggle):
  write the script -> paint and check the pictures -> act the voices -> render -> thumbnail -> upload
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


def _run(series: str, upload: bool, interactive: bool, settings: dict, make, VoiceLimit) -> str:
    records = _records(settings, series)
    open_ones = [r for r in records if not r["published"]]
    if open_ones:
        current = open_ones[0]
        folder = current["folder"]
    else:
        waiting = [r for r in records if r["published"] and datetime.fromisoformat(r["published"]["slot"]) > datetime.now(P.IST)]
        ahead = int(settings.get("pipeline", {}).get("stories_ahead", 2))
        if len(waiting) >= ahead:
            return f"{series}: {len(waiting)} stories are already scheduled; nothing to make today"
        folder = settings["paths"]["episodes"] / f"{series}-{datetime.now(P.IST):%Y-%m-%d}"
        folder.mkdir(parents=True, exist_ok=True)
        current = {"folder": folder, "script": None, "video": False}

    if not (folder / "script.json").exists():
        topic = _next_topic(settings, series, records)
        log.info("▶ writing a new %s story: %s", series, topic)
        titles = [r["script"]["title_ta"] for r in records if r["script"]]
        script = writer.write(series, topic, settings, titles)
        (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("  \"%s\" (%d scenes)", script["title_ta"], len(script["scenes"]))

    try:
        log.info("▶ pictures, voices and video for %s", folder.name)
        make.make(folder, settings)
    except VoiceLimit as e:
        return f"{series}: {folder.name} is waiting for tomorrow's free voice lines ({e})"

    if not upload:
        return f"{series}: {folder.name} is made ({folder / 'video.mp4'}); not uploaded"
    record = P.publish(folder, settings, interactive)
    if record is None:
        return f"{series}: {folder.name} is made, but this series' YouTube channel is not signed in yet"
    return (f"{series}: {folder.name} uploaded https://youtu.be/{record['video_id']} -- public "
            f"{datetime.fromisoformat(record['slot']):%a %d %b %H:%M} IST")


def status() -> list[str]:
    settings, lines = writer.load_settings(), []
    for series in ("adults", "kids"):
        for r in _records(settings, series):
            title = r["script"]["title_ta"] if r["script"] else "(not written yet)"
            if r["published"]:
                state = f"scheduled {datetime.fromisoformat(r['published']['slot']):%a %d %b %H:%M}  https://youtu.be/{r['published']['video_id']}"
            else:
                state = "video made, not uploaded" if r["video"] else "in progress"
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
    s = sub.add_parser("signin")
    s.add_argument("--series", choices=["adults", "kids"], required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "run":
            log.info("✅ %s", run(args.series, upload=not args.no_upload, interactive=not args.scheduled))
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
