"""A book kept as short passages, for a series that retells one passage a day (Ramana series).

  <folder>/passages.jsonl   one passage per line: id, group, work, title, url, text

`group` is the chapter or work the passage comes from: the planner takes the groups in turn, so
consecutive days come from different places in the books. Only texts that may be freely reused
are stored here (public domain / CC0), which is why this file lives in the repository.

Collected once with:  python -m autopilot --series ramana source"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from shorts.log import log

TAMIL = re.compile("[஀-௿]")
PASSAGE_CHARS = (1400, 2600)  # enough for one complete incident or teaching, short enough to stay on it


@dataclass
class Passage:
    id: str
    group: str
    work: str      # the book, with its author: shown as the source under the video
    title: str
    url: str
    text: str

    @property
    def credit(self) -> str:
        return f"{self.work} — \"{self.title}\"" if self.title else self.work


class Store:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "passages.jsonl"

    def passages(self) -> list[Passage]:
        if not self.path.exists():
            return []
        return [Passage(**json.loads(line)) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def save(self, passages: list[Passage]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(p.__dict__, ensure_ascii=False) for p in passages) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def split(paragraphs: list[str], low: int = PASSAGE_CHARS[0], high: int = PASSAGE_CHARS[1]) -> list[str]:
    """Whole paragraphs gathered into passages of about low..high characters."""
    out, current = [], ""
    for para in paragraphs:
        if current and len(current) + len(para) > high:
            out.append(current)
            current = ""
        current = f"{current}\n{para}".strip()
    if current:
        if out and len(current) < low // 2:   # a short tail belongs with what came before it
            out[-1] = f"{out[-1]}\n{current}"
        else:
            out.append(current)
    return out


def paragraphs(page_html: str) -> tuple[list[str], dict[int, str]]:
    """The Tamil paragraphs of a Wikisource page, and the section headings by paragraph number."""
    page_html = re.sub(r"<(style|script|table)\b.*?</\1>", " ", page_html, flags=re.S)
    paras, headings = [], {}
    for tag, inner in re.findall(r"<(p|h[1-4]|center|dd)\b[^>]*>(.*?)</\1>", page_html, flags=re.S):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).replace("​", "").replace("﻿", "").strip()
        if not TAMIL.search(text):
            continue
        if tag != "p" and len(text) < 70:
            headings[len(paras)] = text.strip(" !?.")
        elif len(text) > 40:
            paras.append(text)
    return paras, headings


def _polite(req, waits=(0, 30, 90, 180)) -> str:
    """Wikisource answers 429 when asked too quickly: wait and ask again."""
    for i, wait in enumerate(waits):
        time.sleep(wait)
        try:
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == len(waits) - 1:
                raise
    raise RuntimeError("unreachable")


def collect_wikisource(store: Store, book: str, pages: int, work: str, delay: float = 3.0) -> int:
    """A Tamil Wikisource book whose chapters are the subpages <book>/001-NNN ... NNN-NNN."""
    found = []
    for n in range(1, pages + 1):
        title = f"{book}/{n:03d}-{pages:03d}"
        url = "https://ta.wikisource.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": 2})
        req = urllib.request.Request(url, headers={"User-Agent": "bhakti-shorts/1.0 (personal devotional project)"})
        data = json.loads(_polite(req))
        paras, headings = paragraphs(data.get("parse", {}).get("text", ""))
        heading, start = "", 0
        for i, text in enumerate(split(paras), 1):
            for k in range(start, start + len(text.split("\n"))):   # the last heading at or before this passage
                heading = headings.get(k, heading)
            start += len(text.split("\n"))
            found.append(Passage(f"{book}:{n:03d}:{i:02d}", f"{book}:{n:03d}", work, heading if heading != book else "",
                                 "https://ta.wikisource.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")), text))
        log.info("  %s: %d passages so far", title, len(found))
        time.sleep(delay)
    keep = [p for p in store.passages() if not p.id.startswith(f"{book}:")]
    store.save(keep + found)
    return len(found)
