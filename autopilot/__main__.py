"""Command line.

  python -m autopilot run                  make today's Short and schedule it on YouTube
  python -m autopilot run --no-upload      everything except the upload (to preview)
  python -m autopilot run --publish-now    go public immediately instead of at publish_time
  python -m autopilot check                keys, models, YouTube sign-in (read-only)
  python -m autopilot pictures             paint ~20 new pictures on Kaggle into a review folder
  python -m autopilot source               collect Deivathin Kural chapters (Periyava series), resumable
  python -m autopilot --series periyava run   the Sri Mahaperiyava series (periyava.toml)
  python -m autopilot schedule install     daily Windows task (time from autopilot.toml)
  python -m autopilot schedule remove
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date

from shorts.config import ROOT
from shorts.log import log, setup_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m autopilot", description="Automatic Murugan Shorts")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--series", default="murugan", help="murugan (autopilot.toml) or periyava (periyava.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--no-upload", action="store_true")
    r.add_argument("--publish-now", action="store_true")
    r.add_argument("--force", action="store_true", help="make a new Short even if today's is done")
    r.add_argument("--date", type=date.fromisoformat)
    r.add_argument("--scheduled", action="store_true", help="unattended: never open a browser")
    sub.add_parser("check")
    pc = sub.add_parser("pictures")
    pc.add_argument("--count", type=int, default=20)
    src = sub.add_parser("source")
    src.add_argument("--parts", default="1,2,3,4,5,6,7")
    s = sub.add_parser("schedule")
    s.add_argument("action", choices=["install", "remove", "status"])
    args = p.parse_args(argv)
    setup_logging(args.verbose)

    try:
        if args.cmd == "run":
            from autopilot.run import run

            run(args.date, upload=not args.no_upload, publish_now=args.publish_now, force=args.force,
                interactive=not args.scheduled, series=args.series)
        elif args.cmd == "check":
            return _check(args.series)
        elif args.cmd == "source":
            from autopilot.sources import deivathin_kural as dk

            store = dk.Store(ROOT / "sources" / "deivathin_kural")
            added = store.collect(tuple(int(x) for x in args.parts.split(",")))
            log.info("✅ %d chapters added (%d stored)", added, len(store.chapters()))
        elif args.cmd == "pictures":
            from autopilot.pictures import paint
            from autopilot.settings import load_settings

            paint(load_settings()["paths"]["image_folder"], args.count)
        elif args.cmd == "schedule":
            return _schedule(args.action)
    except Exception as exc:  # noqa: BLE001 -- one readable line for the console and the log
        log.error("Autopilot stopped: %s", exc)
        log.debug("details", exc_info=True)
        return 1
    return 0


def _check(series: str = "murugan") -> int:
    from autopilot import youtube
    from autopilot.settings import api_key, load_settings

    s = load_settings(series=series)
    ok = True
    for provider, key in (("gemini", "GEMINI_API_KEY"), ("openai", "OPENAI_API_KEY"), ("claude", "ANTHROPIC_API_KEY")):
        used = provider in (s["providers"]["writer"], s["providers"].get("fallback_writer"), "gemini")  # gemini: picture descriptions
        have = bool(api_key(key))
        if used and not have and provider in ("gemini", s["providers"]["writer"]):
            ok = False
        log.info("%s %-8s key %s%s", "✓" if have else ("✗" if used else "•"), provider,
                 "found" if have else "missing", "  (in use)" if used else "")
    from autopilot import library

    pictures = library.load(s["paths"]["image_folder"])  # no describe: read-only count
    described = sum(1 for p in pictures if p.info)
    if not pictures:
        ok = False
    log.info("%s pictures: %d in %s (%d described, the rest are described on the next run)",
             "✓" if pictures else "✗", len(pictures), s["paths"]["image_folder"], described)
    try:
        log.info("✓ YouTube sign-in works: channel '%s'", youtube.check_sign_in())
    except Exception as e:  # noqa: BLE001
        ok = False
        log.info("✗ YouTube sign-in: %s", e)
    return 0 if ok else 1


def _schedule(action: str) -> int:
    from autopilot.settings import load_settings

    sched = load_settings()["schedule"]
    name, at = sched["task_name"], sched["time"]
    bat = ROOT / "auto_short.bat"
    if action == "install":
        # StartWhenAvailable: if the laptop was off/asleep at the set time, run at the next chance.
        ps = (f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c \"\"{bat}\" --scheduled\"' "
              f"-WorkingDirectory '{ROOT}';"
              f"$t = New-ScheduledTaskTrigger -Daily -At '{at}';"
              "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries "
              "-AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 6);"
              f"Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t -Settings $s "
              "-Description 'Makes and schedules the daily Murugan Short (autopilot)' -Force | Out-Null")
    elif action == "remove":
        ps = f"Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false"
    else:
        ps = (f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction Stop; $i = $t | Get-ScheduledTaskInfo;"
              "'{0}  next run: {1}  last run: {2}  last result: {3}' -f $t.State, $i.NextRunTime, $i.LastRunTime, $i.LastTaskResult")
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if res.returncode != 0:
        log.error("%s", (res.stderr or res.stdout).strip().splitlines()[0] if (res.stderr or res.stdout) else "failed")
        return 1
    log.info("%s", res.stdout.strip() or {"install": f"Scheduled '{name}' daily at {at}.",
                                          "remove": f"Removed '{name}'."}[action])
    return 0


if __name__ == "__main__":
    sys.exit(main())
