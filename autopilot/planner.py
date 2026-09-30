"""Picks today's topic without asking an AI to guess dates: listed festivals first, then the
weekly Tuesday (செவ்வாய்) tradition, then a rotating everyday theme not used recently.

A grounded series ([content] source = "deivathin_kural") instead retells one chapter a day: the
next unused chapter judged suitable, taking the parts in turn and each part in book order."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class Plan:
    day: date
    theme: str
    festival_ta: str = ""
    festival_en: str = ""
    is_tuesday: bool = False
    source: dict = field(default_factory=dict)  # grounded series: {"id", "credit", "url", "title", "text"}

    def context(self) -> str:
        parts = [f"Date: {self.day.isoformat()} ({self.day.strftime('%A')})."]
        if self.source:
            return " ".join(parts) + (f"\nToday's chapter to retell: {self.source['credit']}\n"
                                      f"Its core teaching (for orientation): {self.theme}\n\n"
                                      f"Chapter text:\n{self.source['text']}")
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

    def used_sources(self, before: date | None = None) -> set[str]:
        """Chapters already retold (on earlier days; a re-run of the same day keeps its chapter)."""
        return {r["source_id"] for r in self.runs
                if r.get("source_id") and (before is None or r["date"] < before.isoformat())}

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


def plan_day(day: date, settings: dict, history: History, judge=None) -> Plan:
    """judge: (system, user, schema) -> dict, used by a grounded series to judge a few more
    chapters when none of the judged ones is left."""
    if settings["content"].get("source") == "deivathin_kural":
        return _chapter_plan(day, settings, history, judge)
    fest = festival_for(day, settings.get("festivals", []))
    if fest:
        return Plan(day, f"{fest['name_en']} festival", fest["name_ta"], fest["name_en"], day.weekday() == 1)
    themes = settings["content"]["themes"]
    recent = set(history.recent_themes(settings["content"]["recent_topics_to_avoid"]))
    fresh = [t for t in themes if t not in recent] or themes  # all used recently: start the cycle again
    theme = random.Random(day.toordinal()).choice(fresh)       # same day -> same pick if re-run
    return Plan(day, theme, is_tuesday=day.weekday() == 1)


def _chapter_plan(day: date, settings: dict, history: History, judge) -> Plan:
    from autopilot.sources import deivathin_kural as dk

    store = dk.Store(settings["paths"]["source"])
    chapters = store.chapters()
    if not chapters:
        raise RuntimeError(f"No Deivathin Kural chapters in {store.path} -- run:  python -m autopilot source")
    used = history.used_sources(before=day)

    def open_chapters():
        verdicts = store.verdicts()
        return [c for c in chapters if verdicts.get(c.id, {}).get("suitable") and c.id not in used], verdicts

    pool, verdicts = open_chapters()
    if len(pool) < 3 and judge and len(verdicts) < len(chapters):
        # judge the next chapters in turn across the parts, a couple of requests' worth
        dk.judge(store, judge, limit=24, order=_part_rotation(chapters))
        pool, verdicts = open_chapters()
    if not pool:
        raise RuntimeError("No suitable Deivathin Kural chapter left to retell (all used or not judged yet)")
    parts = sorted({c.part for c in pool})
    part = parts[day.toordinal() % len(parts)]                      # a different part each day
    chapter = min((c for c in pool if c.part == part), key=lambda c: c.index)  # book order within it
    v = verdicts[chapter.id]
    return Plan(day, v["theme"], source={"id": chapter.id, "credit": chapter.credit, "url": chapter.url,
                                         "title": chapter.title, "text": chapter.text[:12000]})


def _part_rotation(chapters: list) -> list:
    """Chapters ordered 1st of part 1, 1st of part 2, … 2nd of part 1, … (so judging spreads)."""
    by_part: dict[int, list] = {}
    for c in sorted(chapters, key=lambda c: (c.part, c.index)):
        by_part.setdefault(c.part, []).append(c)
    out, i = [], 0
    while any(i < len(v) for v in by_part.values()):
        out += [v[i] for v in by_part.values() if i < len(v)]
        i += 1
    return out
