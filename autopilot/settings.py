"""autopilot.toml + API keys. Keys are read from the environment first, then from the
project's .env and its parent folder's .env. Values are never logged."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from shorts.config import ROOT


SERIES_FILES = {"murugan": "autopilot.toml", "periyava": "periyava.toml"}

# What differs between series, with the Murugan series' values as defaults (autopilot.toml predates
# series, so it doesn't list them).
SERIES_DEFAULTS = {
    "series": {"name": "murugan", "title": "Murugan Short", "output_prefix": "muruganAuto",
               "launcher": "auto_short.bat"},
    "content": {"title_must_contain": ["முருக", "Murugan"],
                "title_never_starts": ["முருகன் அருள் வாக்கு", "முருகன் அருள்வாக்கு", "Murugan"],
                "default_hashtags": ["#முருகன்", "#Murugan", "#TamilDevotional"]},
    "youtube": {"footer": "🙏 தினமும் முருகன் அருள் வாக்கு — Subscribe செய்து பகிருங்கள்.", "playlist_id": ""},
}


def load_settings(path: Path | None = None, series: str = "murugan") -> dict:
    """The series' settings file (autopilot.toml = Murugan, periyava.toml = Sri Mahaperiyava)."""
    if path is None:
        if series not in SERIES_FILES:
            raise ValueError(f"Unknown series '{series}' (choose {', '.join(SERIES_FILES)})")
        path = ROOT / SERIES_FILES[series]
    with open(path, "rb") as f:
        s = tomllib.load(f)
    from shorts.config import deep_merge

    s = deep_merge(SERIES_DEFAULTS, s)
    s["paths"] = {k: (Path(v) if Path(v).is_absolute() else ROOT / v) for k, v in s["paths"].items()}
    return s


def api_key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    for env_file in (ROOT / ".env", ROOT.parent / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def require_key(name: str, what: str) -> str:
    key = api_key(name)
    if not key:
        raise RuntimeError(f"{what} needs {name}: add a line  {name}=...  to {ROOT / '.env'}")
    return key
