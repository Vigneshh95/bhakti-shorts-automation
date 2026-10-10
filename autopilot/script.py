"""What the writer model must return, the prompt that asks for it, and the checks that decide
whether it's safe to publish. The same prompt/schema/validation is used for every provider."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from autopilot.planner import Plan

LINE_SLACK = 8  # characters a line may run over max_line_chars before the draft is rejected

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}},
    "required": ["ok", "issues"],
    "additionalProperties": False,
}


def schema(image_ids: list[str]) -> dict:
    """The writer's output. image_id is limited to today's candidate pictures."""
    return {
        "type": "object",
        "properties": {
            "image_id": {"type": "string", "enum": image_ids},
            "lines": {"type": "array", "items": {"type": "string"}},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "hook_title": {"type": "string"},
            "youtube_title": {"type": "string"},
            "youtube_description": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["image_id", "lines", "keywords", "hook_title", "youtube_title", "youtube_description",
                     "hashtags", "tags"],
        "additionalProperties": False,
    }


SYSTEM = """You write daily YouTube Shorts for the Tamil devotional channel "{channel}".
Format: Lord Murugan speaks a short message of wisdom directly to the viewer, narrated in Tamil
over one devotional picture, with word-by-word captions. About 30-45 seconds.

First choose the ONE picture (image_id) from the list that best fits today's message (when two
fit equally, take the one where the face is larger and closer: it is watched on a phone), then
write the message so it feels made for that picture. If a picture has text painted on it, the
message must agree with that text (or choose another picture).

Write for real reach AND for respect:
- lines: {lmin}-{lmax} short Tamil sentences, spoken by Murugan to "நீ"/"உன்". Line 1 is a hook
  that makes the viewer stay (a striking first statement, or "முருகன் சொல்வது." style). The last
  line is a blessing. Simple, warm, spoken Tamil (a text-to-speech voice will read it).
  Tamil script ONLY: no English letters, no digits (write numbers as Tamil words), no emoji,
  no quotation marks. Each line at most {maxc} characters and ends with a full stop.
- keywords: 1-3 key Tamil words of the message, each copied exactly as it appears in the lines
  (without punctuation). They are shown in gold in the captions.
- Practical, positive guidance. Never: promises of miracles, money or cures; medical, legal or
  financial advice; quotes attributed to scriptures or real people; mocking any person or faith;
  fear or guilt tactics; claims that a festival is today unless the context says so.
- hook_title: 2-4 Tamil words shown on screen for the first seconds.
- youtube_title: at most 70 characters, in Tamil, and different in shape every day. Lead with
  TODAY'S message itself, as the words a viewer would feel or search for (a question such as
  "மனம் தளர்ந்து விட்டதா?", or a striking statement), then "முருகன்" somewhere after it, e.g.
  "கோபம் வரும்போது இதை நினை | முருகன் சொல்லும் வழி". Never begin with a fixed series phrase such
  as "முருகன் அருள் வாக்கு": a channel whose titles all start alike looks mass-produced.
  Honest, no clickbait, no ALL CAPS, no hashtags in the title.
- youtube_description: 2-3 natural Tamil sentences about the message, then 1 English sentence,
  naturally using searched words (Murugan, முருகன், Tamil devotional, today's theme).
- hashtags: 3-5, each starting with #, e.g. #முருகன் #Murugan and one theme hashtag.
- tags: 10-20 relevant search phrases, Tamil and English, only about Murugan / Tamil devotion /
  today's theme. No numbers-only or filler tags.
Return only JSON matching the schema."""

REVIEW_SYSTEM = """You are a careful Tamil editor and reviewer for a respectful Hindu devotional
YouTube channel about Lord Murugan. Check the script and metadata below and return ok=false with
specific issues if ANY of these hold: incorrect or unnatural Tamil; anything disrespectful to
Murugan, Hinduism or any faith; false or unverifiable claims (dates, scripture quotes, miracles,
cures, money); medical, legal or financial advice; misleading or clickbait title; the message
clearly doesn't fit the chosen picture's description. Minor stylistic preferences are not issues."""

_TAMIL_LINE = re.compile(r"^[஀-௿\s.,;!?‌‍-]+$")


@dataclass
class Script:
    image_id: str
    lines: list[str]
    keywords: list[str]
    hook_title: str
    youtube_title: str
    youtube_description: str
    hashtags: list[str]
    tags: list[str]
    provider: str = ""
    review_issues: list[str] = field(default_factory=list)
    source: dict = field(default_factory=dict)  # grounded series: {"id", "credit", "url"} of the retold text

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "image_id", "lines", "keywords", "hook_title", "youtube_title", "youtube_description", "hashtags",
            "tags", "provider", "review_issues", "source")}


def build_prompt(plan: Plan, settings: dict, recent_titles: list[str], pictures: list[tuple[str, str]]) -> tuple[str, str]:
    """pictures: (image_id, description) for today's candidates."""
    c = settings["content"]
    template = settings.get("prompts", {}).get("system") or SYSTEM  # a series can bring its own voice and rules
    system = template.format(channel=c["channel_name"], lmin=c["lines_min"], lmax=c["lines_max"], maxc=c["max_line_chars"])
    user = plan.context() + "\n\nPictures to choose from:\n" + "\n".join(f"- {pid}: {desc}" for pid, desc in pictures)
    if recent_titles:
        user += "\n\nRecent titles on the channel (write something clearly different):\n- " + "\n- ".join(recent_titles[-10:])
    return system, user


def _words(lines: list[str]) -> set[str]:
    return {w.strip(" .,;:!?") for line in lines for w in line.split()}


def review_system(settings: dict) -> str:
    return settings.get("prompts", {}).get("review") or REVIEW_SYSTEM


def tidy(data: dict, settings: dict | None = None) -> dict:
    """Fixes purely mechanical slips in place instead of rejecting a good script over them:
    hashtag formatting/count, punctuation stuck to key words, and a key phrase given where key
    words are wanted (its words that appear in the lines are used instead)."""
    tags, seen = [], set()
    for h in data.get("hashtags", []):
        h = "#" + re.sub(r"[\s#.,;:!?]+", "", str(h))
        if not re.fullmatch(r"#[A-Za-z0-9_஀-௿‌‍]+", h):
            continue  # a stray character from another script (a model glitch): drop that hashtag
        if len(h) > 1 and h.lower() not in seen:
            seen.add(h.lower())
            tags.append(h)
    defaults = (settings or {}).get("content", {}).get("default_hashtags") or ["#முருகன்", "#Murugan", "#TamilDevotional"]
    for default in defaults:
        if len(tags) >= 3:
            break
        if default.lower() not in seen:
            seen.add(default.lower())
            tags.append(default)
    data["hashtags"] = tags[:5]
    in_lines = _words(data.get("lines", []))
    keywords = []
    for k in data.get("keywords", []):
        k = str(k).strip(" .,;:!?")
        parts = [k] if k in in_lines or " " not in k else [w.strip(" .,;:!?") for w in k.split()]
        for w in parts:
            if w and w not in in_lines and len(w) >= 3:
                # the word's dictionary form was given; the lines have it inflected (பிள்ளையார் -> பிள்ளையாரை)
                stem = w.rstrip("்")  # the final pulli goes when an ending is added (ர் + ஐ = ரை)
                w = next((x for x in sorted(in_lines, key=len) if x.startswith(stem)), w)
            if w and w not in keywords and (w in in_lines or len(parts) == 1):
                keywords.append(w)
    found = [w for w in keywords if w in in_lines]
    data["keywords"] = (found or keywords)[:3]  # one that isn't in the lines is dropped if others are
    return data


def validate(data: dict, settings: dict, image_ids: list[str]) -> list[str]:
    """Problems that would make the Short fail or look bad; empty list = publishable."""
    c = settings["content"]
    errors = []
    lines = [l.strip() for l in data.get("lines", []) if l and l.strip()]
    if not c["lines_min"] <= len(lines) <= c["lines_max"]:
        errors.append(f"need {c['lines_min']}-{c['lines_max']} lines, got {len(lines)}")
    for i, line in enumerate(lines, 1):
        if not _TAMIL_LINE.match(line):
            errors.append(f"line {i} has non-Tamil characters (only Tamil script allowed): {line}")
        # The writer is asked for max_line_chars; a few characters over still reads and sounds fine,
        # and isn't worth throwing a whole draft away for (each draft costs two model calls).
        if len(line) > c["max_line_chars"] + LINE_SLACK:
            errors.append(f"line {i} is {len(line)} characters (max {c['max_line_chars']})")
    if data.get("image_id") not in image_ids:
        errors.append(f"image_id must be one of: {', '.join(image_ids)}")
    keywords = data.get("keywords", [])
    missing = [k for k in keywords if k.strip(" .,;:!?") not in _words(lines)]
    if not 1 <= len(keywords) <= 3 or missing:
        errors.append(f"keywords: 1-3 words copied exactly from the lines (not found: {', '.join(missing)})")
    title = data.get("youtube_title", "").strip()
    if not 10 <= len(title) <= 70:
        errors.append(f"youtube_title must be 10-70 characters, got {len(title)}")
    if "#" in title:
        errors.append("youtube_title must not contain hashtags")
    for start in c.get("title_never_starts") or []:
        if title.startswith(start):
            errors.append(f'youtube_title must not begin with the fixed phrase "{start}": lead with the message of the day')
    must = c.get("title_must_contain") or ["முருக", "Murugan"]
    if not any(m in title for m in must):
        errors.append(f"youtube_title must contain one of: {', '.join(must)}")
    tags = data.get("hashtags", [])
    if not 3 <= len(tags) <= 5 or not all(t.startswith("#") and " " not in t for t in tags):
        errors.append("hashtags: 3-5 items, each like #Word (no spaces)")
    if len(data.get("tags", [])) < 5:
        errors.append("tags: at least 5 search phrases")
    if not data.get("hook_title", "").strip():
        errors.append("hook_title is empty")
    return errors


def to_script(data: dict, provider: str) -> Script:
    return Script(
        image_id=data["image_id"],
        lines=[l.strip() for l in data["lines"] if l.strip()],
        keywords=[k.strip(" .,;:!?") for k in data["keywords"]],
        hook_title=data["hook_title"].strip(),
        youtube_title=data["youtube_title"].strip(),
        youtube_description=data["youtube_description"].strip(),
        hashtags=[h.strip() for h in data["hashtags"]],
        tags=_clean_tags(data["tags"]),
        provider=provider,
    )


def _clean_tags(tags: list[str]) -> list[str]:
    out, total = [], 0
    for t in tags:
        t = t.strip().lstrip("#")
        if not t or t.isdigit() or t in out:
            continue
        if total + len(t) + 1 > 450:  # YouTube's tag budget is 500 characters
            break
        out.append(t)
        total += len(t) + 1
    return out
