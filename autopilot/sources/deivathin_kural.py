"""Deivathin Kural (தெய்வத்தின் குரல்), Sri Mahaperiyava's discourses, from the Kanchi Math's
own site kamakoti.org: collected once into a local chapter store the daily writer is grounded in.

  sources/deivathin_kural/chapters.jsonl   one chapter per line: part, index, title, url, text
  sources/deivathin_kural/verdicts.json    per chapter: is it a good daily Short? (judged once)

Collecting is polite (one page a second) and resumable: chapters already stored are skipped, so
a stopped run just continues next time."""
from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from shorts.log import log

BASE = "https://kamakoti.org/tamil/"
PART_INDEXES = {1: "part1index.htm", 2: "part2index.htm", 3: "3dkindex.htm", 4: "part4index.htm",
                5: "5index.htm", 6: "part6index.htm", 7: "part7index.htm"}
PART_NAMES = {1: "முதல் பகுதி", 2: "இரண்டாம் பகுதி", 3: "மூன்றாம் பகுதி", 4: "நான்காம் பகுதி",
              5: "ஐந்தாம் பகுதி", 6: "ஆறாம் பகுதி", 7: "ஏழாம் பகுதி"}
TAMIL = re.compile("[஀-௿]")
MIN_CHARS = 400  # shorter pages are headings or fragments, not a whole talk


@dataclass
class Chapter:
    part: int
    index: int     # order within the part
    title: str
    url: str
    text: str

    @property
    def id(self) -> str:
        return f"{self.part}:{self.url.rsplit('/', 1)[-1]}"

    @property
    def credit(self) -> str:
        return f"தெய்வத்தின் குரல், {PART_NAMES[self.part]} — \"{self.title}\""


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BrahmaNadagam Shorts; one page/s)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def chapter_links(index_html: str) -> list[tuple[str, str]]:
    """(file, title) of each chapter listed on a part's index page, in order."""
    seen, out = set(), []
    for href, label in re.findall(r'href="?([^" >]+)"?[^>]*>(.{0,300}?)</a', index_html, re.S | re.I):
        title = html.unescape(re.sub(r"<[^>]+>|\s+", " ", label)).strip()
        if (href.startswith(("/", "http", "#", "mailto")) or not href.lower().endswith((".htm", ".html"))
                or "index" in href.lower() or not TAMIL.search(title) or href in seen):
            continue
        seen.add(href)
        out.append((href, title))
    return out


def chapter_text(page_html: str) -> str:
    """The talk itself: the long Tamil paragraphs between the page's navigation and its
    'Quick jump' chapter list."""
    s = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", page_html)
    s = re.split(r"(?i)Quick\s*jump", s)[0]
    text = html.unescape(re.sub(r"(?i)<br\s*/?>|</p>", "\n", s))
    text = re.sub(r"<[^>]+>", "\n", text)
    paras = [re.sub(r"\s+", " ", p).strip() for p in text.splitlines()]
    return clean("\n".join(p for p in paras if len(p) > 60 and TAMIL.search(p)))


def clean(text: str) -> str:
    """Drops the page's own title line ("<title> : தெய்வத்தின் குரல் (…பகுதி)"), which the pages
    repeat above the talk, and any repeated paragraph."""
    keep = [p for p in text.split("\n") if "தெய்வத்தின் குரல் (" not in p]
    return "\n".join(dict.fromkeys(keep))


class Store:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "chapters.jsonl"
        self.verdicts_path = folder / "verdicts.json"

    def chapters(self) -> list[Chapter]:
        if not self.path.exists():
            return []
        out, seen = [], set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = Chapter(**json.loads(line))
            if c.url in seen:
                continue
            seen.add(c.url)
            c.text = clean(c.text)
            out.append(c)
        return out

    def verdicts(self) -> dict:
        return json.loads(self.verdicts_path.read_text(encoding="utf-8")) if self.verdicts_path.exists() else {}

    def save_verdicts(self, verdicts: dict) -> None:
        tmp = self.verdicts_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.verdicts_path)

    def collect(self, parts=tuple(PART_INDEXES), delay: float = 1.0) -> int:
        """Downloads every chapter not stored yet. Returns how many were added."""
        self.folder.mkdir(parents=True, exist_ok=True)
        have = {c.url for c in self.chapters()}
        added = 0
        with open(self.path, "a", encoding="utf-8") as out:
            for part in parts:
                links = chapter_links(_get(BASE + PART_INDEXES[part]))
                todo = [(i, f, t) for i, (f, t) in enumerate(links, 1) if BASE + f not in have]
                log.info("  part %d: %d chapters listed, %d to fetch", part, len(links), len(todo))
                for n, (i, file, title) in enumerate(todo, 1):
                    time.sleep(delay)
                    try:
                        text = chapter_text(_get(BASE + file))
                    except OSError as e:
                        log.warning("  %s: %s (skipped; will retry next time)", file, e)
                        continue
                    if len(text) < MIN_CHARS:
                        continue
                    out.write(json.dumps({"part": part, "index": i, "title": title, "url": BASE + file,
                                          "text": text}, ensure_ascii=False) + "\n")
                    out.flush()
                    added += 1
                    if n % 50 == 0:
                        log.info("    …%d/%d", n, len(todo))
        return added


JUDGE_SYSTEM = """You select chapters of Deivathin Kural (discourses of Sri Chandrasekharendra
Saraswathi Mahaswamigal of Kanchi) for a daily 40-second Tamil YouTube Short that retells one
chapter's essence in simple words for everyone.

For each chapter (by its id) return: theme (2-5 English words), a one-sentence English summary of
its core teaching, and suitable=true only if the chapter carries a clear, practical, universal
message an ordinary person of any background can apply today (e.g. love, devotion, kindness,
humility, simple living, charity, truthfulness, discipline, mother, guru, prayer, peace of mind,
service, the meaning of a festival or a deity told as a life lesson). suitable=false for chapters
mainly about caste/varna duties or who may do what by birth, detailed ritual or dietary rules,
debates against other schools or faiths, dense philosophy that cannot be made simple in six
sentences, history/linguistics without a life lesson, or anything that could hurt or divide."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"chapters": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "theme": {"type": "string"}, "summary": {"type": "string"},
                       "suitable": {"type": "boolean"}},
        "required": ["id", "theme", "summary", "suitable"], "additionalProperties": False}}},
    "required": ["chapters"], "additionalProperties": False,
}


def judge(store: Store, complete_json, limit: int | None = None, batch: int = 12, order: list | None = None) -> int:
    """Judges chapters not judged yet (a few requests a day fit the free tier). `complete_json`
    is (system, user, schema) -> dict. Returns how many were judged."""
    verdicts = store.verdicts()
    todo = [c for c in (order or store.chapters()) if c.id not in verdicts][:limit]
    done = 0
    for start in range(0, len(todo), batch):
        group = todo[start:start + batch]
        user = "\n\n".join(f"id: {c.id}\ntitle: {c.title}\ntext: {c.text[:1500]}" for c in group)
        result = complete_json(JUDGE_SYSTEM, user, JUDGE_SCHEMA)
        for r in result.get("chapters", []):
            if any(r["id"] == c.id for c in group):
                verdicts[r["id"]] = {k: r[k] for k in ("theme", "summary", "suitable")}
                done += 1
        store.save_verdicts(verdicts)
    return done
