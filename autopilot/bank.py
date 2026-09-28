"""Spare, already-reviewed scripts for days when every AI writer is down (e.g. Gemini
overloaded all evening and no OpenAI credit). On good days the autopilot tops the bank up
with one extra script for a future theme; on a bad day it uses the oldest spare instead of
losing the Short. Spares passed the same checks and review as any other script."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from autopilot.script import Script
from shorts.log import log


class Bank:
    def __init__(self, folder: Path):
        self.folder = folder

    def _files(self) -> list[Path]:
        return sorted(self.folder.glob("*.json")) if self.folder.exists() else []

    def size(self) -> int:
        return len(self._files())

    def themes(self) -> list[str]:
        out = []
        for f in self._files():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")).get("theme", ""))
            except ValueError:
                pass
        return out

    def add(self, script: Script, theme: str, day: date) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        n = self.size() + 1
        path = self.folder / f"{day.isoformat()}_{n:02d}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**script.to_dict(), "theme": theme, "written": day.isoformat()},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def take(self) -> tuple[Script, str] | None:
        """Oldest spare (removed from the bank), with its theme; None if the bank is empty."""
        for f in self._files():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                theme = data.pop("theme", "")
                written = data.pop("written", "")
                script = Script(**data)
            except (ValueError, TypeError) as e:
                log.warning("  skipping unreadable spare script %s (%s)", f.name, e)
                f.unlink()
                continue
            f.unlink()
            log.info("  using a spare script written on %s (theme: %s)", written, theme)
            return script, theme
        return None
