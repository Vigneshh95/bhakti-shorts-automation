"""Listens to every spoken clip of a story and reports what was actually said.

The speech models sometimes say more than the line: they read their English acting directions
aloud, add a remark, or repeat the line. A length check cannot catch a short extra sentence, so
each clip is heard by a Gemini model (free text allowance, several clips per request), which
writes down what it hears; a clip that contains anything but its own Tamil line is flagged."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

LISTEN_SYSTEM = """You are checking the recordings of a Tamil audio drama. For each numbered clip you are
given the line the actor was supposed to say. Listen to the clip and report:
- heard: everything spoken in the clip, written exactly as heard, including any words before or
  after the expected line. Tamil speech is written in Tamil script, INCLUDING the English words that
  Tamil speakers use inside Tamil sentences (ஆபீஸ், டீ, சாரி, போன்...). Use English letters ONLY for
  speech that is actually in the English language (English sentences, instructions read aloud).
- extra: true if the clip contains ANY speech besides the expected line: English words or sentences,
  stage directions or descriptions read aloud, a speaker's name read aloud, commentary, the line
  said twice, or a different sentence. false only if it is just the expected line (small
  differences of pronunciation or one changed word do not count).
- where: "start", "end", "both", "middle" or "none": where the extra speech is.
- missing: true if part of the expected line was not spoken."""
LISTEN_SCHEMA = {"type": "object", "properties": {"clips": {"type": "array", "items": {
    "type": "object", "properties": {"n": {"type": "integer"}, "heard": {"type": "string"}, "extra": {"type": "boolean"},
                                     "where": {"type": "string"}, "missing": {"type": "boolean"}},
    "required": ["n", "heard", "extra", "where", "missing"]}}},
    "required": ["clips"]}
_LATIN = re.compile(r"[A-Za-z]{3,}")


def listen(clips: list[tuple[Path, str]], settings: dict, batch: int = 6) -> list[dict]:
    """clips: (wav, expected text). Returns one report per clip, in order: heard, extra, where,
    missing. A clip no model could hear is reported with heard = None."""
    import urllib.error
    import urllib.request

    from autopilot.settings import api_key

    key = api_key("GEMINI_API_KEY_STORIES") or api_key("GEMINI_API_KEY")
    models = [settings["models"]["gemini_text"], *settings["models"].get("gemini_text_fallback", [])]
    out: list[dict] = []
    for start in range(0, len(clips), batch):
        group = clips[start:start + batch]
        parts = []
        for i, (path, text) in enumerate(group, 1):
            parts += [{"text": f"Clip {i}. Expected line: {text}"},
                      {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(Path(path).read_bytes()).decode()}}]
        body = {"systemInstruction": {"parts": [{"text": LISTEN_SYSTEM}]}, "contents": [{"parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": LISTEN_SCHEMA, "temperature": 0}}
        got = None
        for model in models:
            req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                         data=json.dumps(body).encode(), headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            try:
                data = json.load(urllib.request.urlopen(req, timeout=240))
                got = {c["n"]: c for c in json.loads(data["candidates"][0]["content"]["parts"][0]["text"])["clips"]}
                break
            except (urllib.error.URLError, KeyError, ValueError, IndexError, TimeoutError):
                continue
        for i in range(1, len(group) + 1):
            c = (got or {}).get(i)
            if c is None:
                out.append({"heard": None, "extra": False, "where": "none", "missing": False})
            else:
                c["extra"] = bool(c["extra"]) or bool(_LATIN.search(c["heard"]))   # any English word heard counts
                out.append(c)
    return out


def has_english(heard: str) -> bool:
    """English words in what was heard (a Tamil story has none; English loan words like "ஆபீஸ்" are
    written in Tamil script and don't count)."""
    return bool(_LATIN.search(heard or ""))
