"""Story episodes: baby Murugan as a friend and guide, told as an illustrated story.

Two series share this format:
  kids    "குட்டி முருகன் கதைகள்"   for children of 4-10 with a parent (5-6 min)
  adults  "முருகன் சொன்ன வழி"       for viewers of 15 and up (6-8 min)

A writer model returns the whole episode as scenes; each scene has the lines spoken in it (with
who speaks) and a description of the picture to paint. The characters are fixed (CAST), so they
look and sound the same in every episode. A second pass reviews the script before anything is made."""
from __future__ import annotations

import re

# The fixed cast. `look` goes into every picture prompt that shows the character (so the painter
# draws the same person each time); `voice` is a style in stories.toml.
CAST = {
    "narrator": {"name": "கதைசொல்லி", "voice": "narrator", "look": ""},
    "murugan": {"name": "குட்டி முருகன்", "voice": "murugan",
                "look": "baby Lord Murugan, an adorable chubby toddler god with big bright kind eyes, curly dark hair, "
                        "ornate golden crown, small red and white tilak, golden chest armour and jewellery, orange-red "
                        "dhoti, holding a small golden Vel spear"},
    "ilango": {"name": "இளங்கோ", "voice": "boy",
               "look": "Ilango, an 8-year-old Tamil boy with short neat black hair, round face, bright eyes, wearing a "
                       "blue half-sleeve shirt and khaki shorts"},
    "kuzhali": {"name": "குழலி", "voice": "girl",
                "look": "Kuzhali, a 6-year-old Tamil girl with two long plaits tied with red ribbons, a small bindi, "
                        "wearing a yellow pavadai (long skirt) and green blouse"},
    "paatti": {"name": "ஔவை பாட்டி", "voice": "paatti",
               "look": "Avvai Paatti, a gentle Tamil grandmother in her seventies with silver hair in a bun, round "
                       "spectacles, a maroon cotton saree, warm smile"},
    "person": {"name": "", "voice": "adult", "look": ""},   # adults series: this episode's person (described per episode)
    "peacock": {"name": "மயில்", "voice": "", "look": "a friendly bright blue peacock with a green train"},
    # people inside the story Murugan tells (described in that scene's picture, different each episode)
    "tale_child": {"name": "", "voice": "tale_child", "look": ""},
    "tale_woman": {"name": "", "voice": "tale_woman", "look": ""},
    "tale_man": {"name": "", "voice": "adult", "look": ""},
}
SPEAKERS = ["narrator", "murugan", "ilango", "kuzhali", "paatti", "person", "tale_child", "tale_woman", "tale_man"]

STYLE = ("Warm, glowing traditional South Indian storybook illustration, soft painterly finish, rich golden and green "
         "colours, gentle light, expressive friendly faces, wide 16:9 composition, no text, no letters, no watermark.")

SCHEMA = {
    "type": "object",
    "properties": {
        "title_ta": {"type": "string"}, "title_en": {"type": "string"},
        "lesson_ta": {"type": "string"},
        "source_number": {"type": "integer"},
        "source_line_ta": {"type": "string"}, "source_name_ta": {"type": "string"}, "source_meaning_ta": {"type": "string"},
        "person_look": {"type": "string"},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "picture": {"type": "string"},
                "characters": {"type": "array", "items": {"type": "string", "enum": list(CAST)}},
                "lines": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"speaker": {"type": "string", "enum": SPEAKERS}, "text": {"type": "string"}},
                    "required": ["speaker", "text"], "additionalProperties": False}},
            },
            "required": ["picture", "characters", "lines"], "additionalProperties": False}},
        "action_ta": {"type": "string"}, "question_ta": {"type": "string"},
        "youtube_title": {"type": "string"}, "youtube_description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}}, "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title_ta", "title_en", "lesson_ta", "source_number", "source_line_ta", "source_name_ta", "source_meaning_ta",
                 "person_look", "scenes", "action_ta", "question_ta", "youtube_title", "youtube_description",
                 "hashtags", "tags"],
    "additionalProperties": False,
}

COMMON = """You write episodes of an illustrated Tamil story series for the devotional YouTube channel
"{channel}". In every episode baby Lord Murugan appears as a loving friend and guide, with his
peacock. He never scolds, never frightens, never promises miracles, money or cures: he helps people
see clearly and gives them courage, usually by telling a short story.

The episode is a list of scenes. Each scene is ONE picture with the lines spoken over it.
- picture: an English description of exactly what the painter should show: who is there, what they
  are doing, their expression, the place, the time of day. Do not describe the characters' fixed
  appearance (it is added automatically); name them: Murugan, Ilango, Kuzhali, Paatti, the peacock,
  or "the person". One clear moment per picture; at most three characters in a picture.
- characters: who is visible in that picture.
- lines: 2-4 spoken lines for that scene. speaker is who says it. Natural spoken Tamil that a
  voice model will read aloud: Tamil script only (no English letters, no digits, no emoji, no
  quotation marks), each line at most {maxc} characters, ending with a full stop or question mark.
  The narrator tells the story; characters speak their own words. People inside the story that
  Murugan tells speak as tale_child, tale_woman or tale_man (never as "person" in the children's
  series), and their appearance is described in that scene's picture.

The lesson must rest on ONE line of Avvaiyar's Aathichoodi, chosen from the numbered list you are
given: return its number (source_number) and copy the line exactly (source_line_ta). A line that
is not in the list is rejected -- never write a line from memory. source_name_ta is "ஆத்திசூடி".
The story Murugan tells may be a well-known one about him (Avvaiyar and the fruit, the mango and
the journey round the world, teaching the meaning of Om) or a simple new tale; if it is a new
tale, do not present it as scripture.

Also return: title_ta and title_en; lesson_ta (one sentence); source_line_ta (the exact line),
source_name_ta (where it is from) and source_meaning_ta (its meaning in one simple sentence);
action_ta (one small thing to do today); question_ta (one question to talk about);
youtube_title (at most 80 characters, Tamil first then a short English part, honest, no hashtags);
youtube_description (3-4 Tamil sentences then 1-2 English sentences, naming the lesson and source);
hashtags (3-5); tags (10-20 search phrases, Tamil and English).
Return only JSON matching the schema."""

KIDS = COMMON + """

THIS SERIES: "குட்டி முருகன் கதைகள்", for children of 4-10 watching with a parent.
Cast: Ilango (a boy of 8), his sister Kuzhali (6), their grandmother Avvai Paatti, Murugan, the peacock.
Shape, {smin}-{smax} scenes in all:
1. A real moment from a child's day where today's problem shows itself (2-3 scenes).
2. Murugan and the peacock arrive, playful and kind (1-2 scenes).
3. Murugan tells a short story that fits (5-7 scenes); its pictures show the story's own characters.
4. The child tries again and it goes better (2-3 scenes).
5. What we learned: Paatti or Murugan says the source line; the narrator gives its meaning, the
   small thing to do today and the question (1-2 scenes).
Very simple words and short sentences. Warm and a little funny. Nothing frightening, no violence,
no punishment, nobody is shamed: the child is good and is learning. person_look: empty string.
Today's problem: {topic}."""

ADULTS = COMMON + """

THIS SERIES: "முருகன் சொன்ன வழி", for viewers from 15 to 80.
One person today, with an ordinary Tamil name and life (a student, a young mother, a shopkeeper, a
driver, a grandfather...), facing a problem of the world as it is now. Use speaker "person" for
them, and give person_look: one English sentence describing their appearance, so every picture
shows the same person.
Shape, {smin}-{smax} scenes in all:
1. A specific, true-to-life moment that shows the problem (2-3 scenes). Make the viewer think
   "that is me".
2. Baby Murugan appears, simple and unhurried, and listens (1-2 scenes).
3. He answers with a short story from our tradition (5-7 scenes).
4. The person sees it differently and takes one small, real step (2-3 scenes).
5. The source line, its meaning, one practical thing to do today, one question to think about (1-2 scenes).
Respectful and calm, never preachy. No medical, legal or financial advice; no blaming of any
group; nothing about caste. Today's problem: {topic}."""

REVIEW = """You are a careful Tamil editor and a parent. Check this story episode and return
ok=false with specific issues if ANY of these hold: incorrect or unnatural Tamil; anything
frightening, violent, shaming or unsuitable for the audience named below; promises of miracles,
money or cures; medical, legal or financial advice; a quotation that is not the real, exact line
from the named source, or a wrong meaning for it; anything disrespectful to Murugan, Hinduism or
any faith or group; a story that does not actually lead to the stated lesson; a picture description
that shows something the lines do not. Minor stylistic preferences are not issues.
Audience: {audience}."""

REVIEW_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}},
                 "required": ["ok", "issues"], "additionalProperties": False}

_TAMIL = re.compile(r"^[஀-௿\s.,;!?‌‍-]+$")


def aathichoodi() -> list[dict]:
    """Avvaiyar's 109 lines, as on Tamil Wikisource (stories/sources/aathichoodi.json)."""
    import json
    from pathlib import Path

    return json.loads((Path(__file__).parent / "sources" / "aathichoodi.json").read_text(encoding="utf-8"))["lines"]


def source_list() -> str:
    rows = [f"{x['n']}. {x['line']} -- {x['gloss']}" for x in aathichoodi()]
    return "\n".join(["Aathichoodi (number. line -- what it means):", *rows])


def _plain(text: str) -> str:
    return re.sub(r"[\s.,;:!?‌‍]+", "", text)


def system_prompt(series: str, settings: dict, topic: str) -> str:
    c = settings["content"]
    template = KIDS if series == "kids" else ADULTS
    return template.format(channel=c["channel_name"], maxc=c["max_line_chars"], smin=c["scenes_min"],
                           smax=c["scenes_max"], topic=topic)


def validate(data: dict, settings: dict) -> list[str]:
    c = settings["content"]
    errors = []
    scenes = data.get("scenes", [])
    if not c["scenes_min"] <= len(scenes) <= c["scenes_max"] + 2:
        errors.append(f"need {c['scenes_min']}-{c['scenes_max']} scenes, got {len(scenes)}")
    for i, sc in enumerate(scenes, 1):
        if len(sc.get("picture", "")) < 30:
            errors.append(f"scene {i}: the picture description is too short")
        if not sc.get("lines"):
            errors.append(f"scene {i} has no lines")
        for line in sc.get("lines", []):
            text = line.get("text", "").strip()
            if not _TAMIL.match(text):
                errors.append(f"scene {i}: only Tamil script is allowed in a line: {text}")
            if len(text) > c["max_line_chars"] + 10:
                errors.append(f"scene {i}: a line is {len(text)} characters (max {c['max_line_chars']})")
    real = {x["n"]: x["line"] for x in aathichoodi()}
    n, quoted = data.get("source_number"), _plain(data.get("source_line_ta", ""))
    if n not in real or _plain(real[n]) != quoted:
        errors.append(f"source_line_ta must be copied exactly from the Aathichoodi list with its number "
                      f"(got number {n}: {data.get('source_line_ta', '')!r})")
    else:
        data["source_line_ta"], data["source_name_ta"] = real[n], "ஆத்திசூடி"
        # the line may be recited anywhere in the episode, but only in its real wording
        spoken = _plain(" ".join(l.get("text", "") for sc in scenes for l in sc.get("lines", [])))
        if quoted not in spoken:
            errors.append(f"the Aathichoodi line {real[n]!r} must be said, word for word, in the closing scene")
    if not 10 <= len(data.get("youtube_title", "")) <= 90:
        errors.append("youtube_title must be 10-90 characters")
    return errors


def picture_prompt(scene: dict, person_look: str = "") -> str:
    """The full prompt for one scene: the moment, each visible character's fixed look, the style."""
    looks = []
    for who in scene.get("characters", []):
        look = person_look if who == "person" else CAST.get(who, {}).get("look", "")
        if look:
            looks.append(look)
    cast = " Characters: " + "; ".join(looks) + "." if looks else ""
    return f"{scene['picture'].strip()}{cast} {STYLE}"
