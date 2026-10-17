"""Pause and resume the cloud pipelines from the laptop.

The pauses live in the private files (pauses.json in the assets repository), which every pipeline
reads before it does anything: a paused pipeline starts, says "Skipped: this pipeline is PAUSED" and
stops in seconds. Nothing is lost; resuming carries on where it left off.

  python -m autopilot pause short-murugan      (or: all)
  python -m autopilot resume short-murugan     (or: all)
  python -m autopilot pauses                   what is paused now
pipeline_pause.bat does the same with a menu."""
from __future__ import annotations

import json
from datetime import datetime

from autopilot import sync
from shorts.log import log

PIPELINES = {
    "short-murugan": "Short - Murugan (BrahmaNadagam, Mon/Thu/Sun 18:30)",
    "short-periyava": "Short - Mahaperiyava (BrahmaNadagam, Tue/Fri 18:30)",
    "short-krishna": "Short - Krishna (BrahmaNadagam, Wed/Sat 18:30)",
    "short-kids": "Short - Kids channel (every day 17:30)",
    "story-adults": "Story - Grown-ups (BrahmaNadagam)",
    "story-kids": "Story - Kids (kids' channel)",
    "all": "ALL pipelines at once",
}


def _path():
    return sync.CLONE / "pauses.json"


def current() -> dict:
    sync.pull()
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_paused(name: str, paused: bool) -> str:
    if name not in PIPELINES:
        raise ValueError(f"unknown pipeline '{name}' (choose from: {', '.join(PIPELINES)})")
    if not sync.available():
        raise RuntimeError("the private files are not on this laptop (.cache/assets_repo): run send_pictures_to_cloud.bat once")
    p = current()
    if paused:
        p[name] = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        p.pop(name, None)
    _path().write_text(json.dumps(p, indent=1), encoding="utf-8")
    sync._git("add", "pauses.json")
    sync._git("-c", "user.name=laptop", "-c", "user.email=laptop@users.noreply.github.com", "commit", "-q", "-m",
              f"{'pause' if paused else 'resume'} {name}")
    res = sync._git("push", "-q")
    if res.returncode != 0:
        raise RuntimeError(f"couldn't save the change to the private files: {(res.stderr or res.stdout).strip()[-200:]}")
    what = PIPELINES[name]
    return f"{what}: {'PAUSED (it will skip every run until resumed)' if paused else 'resumed'}"


def report() -> list[str]:
    p = current()
    if not p:
        return ["nothing is paused: every pipeline runs as scheduled"]
    return [f"PAUSED since {when}: {PIPELINES.get(name, name)}" for name, when in p.items()]
