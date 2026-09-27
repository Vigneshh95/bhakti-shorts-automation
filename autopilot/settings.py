"""autopilot.toml + API keys. Keys are read from the environment first, then from the
project's .env and its parent folder's .env. Values are never logged."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from shorts.config import ROOT


def load_settings(path: Path | None = None) -> dict:
    with open(path or ROOT / "autopilot.toml", "rb") as f:
        s = tomllib.load(f)
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
