"""The collected texts every grounded series is retold from: complete, without duplicates, Tamil,
without leftover web markup. (A broken collector would otherwise feed the writer empty or garbled text.)"""
import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TAMIL = re.compile("[஀-௿]")
SOURCES = [("autopilot/sources/data/ramana/passages.jsonl", "id", ["id", "group", "work", "url", "text"], 300),
           ("sources/deivathin_kural/chapters.jsonl", "url", ["part", "index", "title", "url", "text"], 400)]


@pytest.mark.parametrize("path,key,need,min_chars", SOURCES)
def test_collected_text_is_complete_unique_and_tamil(path, key, need, min_chars):
    f = ROOT / path
    if not f.exists():
        pytest.skip(f"{path} is not on this machine (kept out of the public repository)")
    rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, "the collection is empty"
    assert not [r for r in rows if any(not r.get(k) for k in need)], "rows with missing fields"
    assert not [k for k, n in Counter(r[key] for r in rows).items() if n > 1], "duplicate rows"
    assert all(len(r["text"]) >= min_chars for r in rows), "a row too short to retell"
    letters = lambda t: len(re.sub(r"\s", "", t))  # noqa: E731
    assert all(len(TAMIL.findall(r["text"])) >= 0.5 * letters(r["text"]) for r in rows), "a row that is mostly not Tamil"
    assert not [r for r in rows if re.search(r"<[a-z/][^>]*>|&[a-z]+;", r["text"])], "leftover HTML in the text"
