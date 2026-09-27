"""Command line.

  python -m shorts make episodes/2026-09-27            build one Short
  python -m shorts make episodes/2026-09-27 --preset fast --voice male
  python -m shorts new 2026-09-27                      create an episode folder to fill in
  python -m shorts check                               verify FFmpeg, Quick Sync, models, fonts
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from shorts.config import ROOT, load_config
from shorts.log import log, setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shorts", description="Murugan Shorts generator")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    mk = sub.add_parser("make", help="build a Short from an episode folder")
    mk.add_argument("episode", type=Path)
    mk.add_argument("--preset", choices=["fast", "balanced", "best"])
    mk.add_argument("--voice", choices=["baby", "young_male", "male"])
    mk.add_argument("--date", help="date used in the output file name (default: today)")
    mk.add_argument("--output", type=Path, help="exact output path (default: Final/muruganShorts_<date>.mp4)")
    up = mk.add_mutually_exclusive_group()
    up.add_argument("--upload", action="store_true", help="upload to YouTube when done (autouploadmurugan.py)")
    up.add_argument("--upload-dry-run", action="store_true", help="show the YouTube title/tags/description, don't upload")

    new = sub.add_parser("new", help="create an episode folder")
    new.add_argument("name")

    sub.add_parser("check", help="check that everything the pipeline needs is in place")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    try:
        if args.cmd == "make":
            from shorts.pipeline import make_short

            episode = resolve_episode(args.episode)
            result = make_short(episode, args.preset, args.date, args.voice, args.output)
            if args.upload or args.upload_dry_run:
                from shorts.upload import upload_video

                upload_video(result.output, dry_run=args.upload_dry_run)
        elif args.cmd == "new":
            return _new_episode(args.name)
        elif args.cmd == "check":
            return _check()
    except (FileNotFoundError, ValueError) as exc:
        log.error("%s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001 -- last-resort: a readable message instead of a bare traceback
        log.exception("Failed: %s", exc)
        return 1
    return 0


def resolve_episode(arg: Path) -> Path:
    """Accepts an absolute path, a path relative to where you are, a path relative to
    this project ("episodes/2026-09-27"), or just the episode name ("2026-09-27") -- so
    make_short.bat works no matter which folder it's started from."""
    if arg.is_absolute():
        return arg
    candidates = [Path.cwd() / arg, ROOT / arg, load_config()["paths"]["episodes"] / arg]
    return next((c for c in candidates if c.is_dir()), candidates[0])


def _new_episode(name: str) -> int:
    cfg = load_config()
    folder = cfg["paths"]["episodes"] / name
    if folder.exists():
        log.error("%s already exists", folder)
        return 2
    (folder / "images").mkdir(parents=True)
    (folder / "lines.txt").write_text("# One Tamil sentence per line. Lines starting with # are ignored.\n",
                                      encoding="utf-8")
    (folder / "episode.toml").write_text('[episode]\ntitle = ""   # hook title; empty = first line\n\n'
                                         '# Any config.toml setting can be overridden here, e.g.\n'
                                         '# [voice]\n# style = "male"\n', encoding="utf-8")
    log.info("Created %s -- add lines to lines.txt and images to images/, then run:", folder)
    log.info("  python -m shorts make %s", folder.relative_to(ROOT))
    return 0


def _check() -> int:
    from shorts import ffmpeg

    cfg = load_config()
    ok = True
    for key in ("ffmpeg", "ffprobe", "checkpoints", "fonts"):
        p = cfg["paths"][key]
        good = bool(p and p.exists())
        ok &= good
        log.info("%s %-11s %s", "✓" if good else "✗", key, p)
    if cfg["paths"]["ffmpeg"] and cfg["paths"]["ffmpeg"].exists():
        qsv = ffmpeg.qsv_works(cfg["paths"]["ffmpeg"])
        log.info("%s Intel Quick Sync %s", "✓" if qsv else "•", "available" if qsv else "not available (x264 will be used)")
    bgm = cfg["paths"].get("bgm")
    log.info("%s background music %s", "✓" if bgm and bgm.exists() else "•", bgm or "(none)")
    log.info("free disk: %.1f GB", shutil.disk_usage(ROOT).free / 2**30)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
