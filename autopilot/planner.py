"""Picks today's topic without asking an AI to guess dates: listed festivals first, then the
weekly Tuesday (செவ்வாய்) tradition, then a rotating everyday theme not used recently."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Plan:
    day: date
    theme: str
    festival_ta: str = ""
    festival_en: str = ""
    is_tuesday: bool = False

    def context(self) -> str:
        parts = [f"Date: {self.day.isoformat()} ({self.day.strftime('%A')})."]
        if self.festival_en:
            parts.append(f"Today is {self.festival_en} ({self.festival_ta}), a Murugan festival: make the message about it.")
        elif self.is_tuesday:
            parts.append("Today is Tuesday (செவ்வாய்க்கிழமை), traditionally Murugan's day; you may mention this.")
        parts.append(f"Theme: {self.theme}.")
        return " ".join(parts)


class History:
    """Run history: what was made and uploaded each day (topic memory + double-upload guard)."""

    def __init__(self, path: Path):
        self.path = path
        self.runs: list[dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.runs, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def recent_themes(self, n: int) -> list[str]:
        return [r["theme"] for r in self.runs[-n:]]

    def recent_titles(self, n: int) -> list[str]:
        return [r.get("title", "") for r in self.runs[-n:] if r.get("title")]

    def image_usage(self) -> dict[str, list[str]]:
        """picture digest -> dates it was used (made into a video)."""
        usage: dict[str, set[str]] = {}
        for r in self.runs:
            if r.get("image_digest"):
                usage.setdefault(r["image_digest"], set()).add(r["date"])  # a resumed day counts once
        return {k: sorted(v) for k, v in usage.items()}

    def last_image(self, before: date) -> str | None:
        """Digest of the most recent picture used before `before` (so it isn't repeated next day)."""
        prior = [r for r in self.runs if r.get("image_digest") and r["date"] < before.isoformat()]
        # the LAST record of the latest day (a day can have several runs, e.g. previews)
        return max(prior, key=lambda r: (r["date"], r.get("made_at", "")))["image_digest"] if prior else None

    def uploads_on(self, day: date) -> list[dict]:
        return [r for r in self.runs if r.get("date") == day.isoformat() and r.get("video_id")]

    def add(self, record: dict) -> None:
        self.runs.append(record)
        self.save()


def festival_for(day: date, festivals: list[dict]) -> dict | None:
    for f in festivals:
        start = date.fromisoformat(f["date"])
        end = date.fromisoformat(f.get("until", f["date"]))
        if start <= day <= end:
            return f
    return None


def plan_day(day: date, settings: dict, history: History) -> Plan:
    fest = festival_for(day, settings.get("festivals", []))
    if fest:
        return Plan(day, f"{fest['name_en']} festival", fest["name_ta"], fest["name_en"], day.weekday() == 1)
    themes = settings["content"]["themes"]
    recent = set(history.recent_themes(settings["content"]["recent_topics_to_avoid"]))
    fresh = [t for t in themes if t not in recent] or themes  # all used recently: start the cycle again
    theme = random.Random(day.toordinal()).choice(fresh)       # same day -> same pick if re-run
    return Plan(day, theme, is_tuesday=day.weekday() == 1)
