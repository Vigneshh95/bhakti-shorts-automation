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
                        "ornate golden crown, forehead marked with three horizontal white lines of sacred ash and "
                        "one small round red dot at their centre, golden chest "
                        "armour and jewellery, orange-red dhoti, holding a small golden Vel spear"},
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
    "peacock": {"name": "மயில்", "voice": "", "look": "one single friendly bright blue peacock bird with a green train"},
    # people inside the story Murugan tells (described in that scene's picture, different each episode)
    "tale_child": {"name": "", "voice": "tale_child", "look": ""},
    "tale_woman": {"name": "", "voice": "tale_woman", "look": ""},
    "tale_man": {"name": "", "voice": "adult", "look": ""},
}
# People inside Murugan's tale: up to four per episode, each listed in the script's tale_cast with
# a kind, which gives them a fitting voice (two men in one tale still sound different: TALE_SHIFT).
TALE_IDS = ["tale_1", "tale_2", "tale_3", "tale_4"]
TALE_KINDS = {"boy": "tale_child", "girl": "girl", "woman": "tale_woman", "man": "adult",
              "old_woman": "paatti", "old_man": "old_man"}
TALE_SHIFT = {"tale_1": 0.0, "tale_2": 1.6, "tale_3": -1.6, "tale_4": 0.8}   # semitones
for _id in TALE_IDS:
    CAST[_id] = {"name": "", "voice": "", "look": ""}
SPEAKERS = ["narrator", "murugan", "ilango", "kuzhali", "paatti", "person", *TALE_IDS]

# Image painters don't understand "no": naming a thing, even to forbid it, tends to paint it (a
# sentence about peacocks here put peacocks on the sofa in scenes that had none). So this and the
# cast's looks say only what SHOULD be in the picture.
STYLE = ("Warm, glowing South Indian storybook illustration in one consistent soft stylised animation style for "
         "everyone in the picture; grown-ups have adult faces, adult height and adult proportions. Soft painterly "
         "finish, rich golden and green colours, gentle light, expressive friendly faces, wide 16:9 composition, "
         "clean uncluttered background.")
STYLE_SCENERY = ("Warm, glowing South Indian storybook illustration, soft painterly finish, rich golden and green "
                 "colours, gentle light, wide 16:9 composition, a quiet still scene of objects and scenery only.")

SCHEMA = {
    "type": "object",
    "properties": {
        "title_ta": {"type": "string"}, "title_en": {"type": "string"},
        "lesson_ta": {"type": "string"},
        "source_number": {"type": "integer"},
        "source_line_ta": {"type": "string"}, "source_name_ta": {"type": "string"}, "source_meaning_ta": {"type": "string"},
        "person_look": {"type": "string"},
        "tale_cast": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string", "enum": TALE_IDS},
                           "kind": {"type": "string", "enum": list(TALE_KINDS)},
                           "name": {"type": "string"}, "look": {"type": "string"}},
            "required": ["id", "kind", "name", "look"], "additionalProperties": False}},
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
                 "person_look", "tale_cast", "scenes", "action_ta", "question_ta", "youtube_title", "youtube_description",
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
  or "the person". One clear moment per picture; at most three characters in a picture. Never ask
  for writing, letters, a title card or a quotation in a picture (painters garble Tamil letters);
  the captions show the words.
- characters: who is visible in that picture.
- lines: 3-5 spoken lines for that scene. speaker is who says it. Natural spoken Tamil that a
  voice model will read aloud: Tamil script only (no English letters, no digits, no emoji, no
  quotation marks), each line at most {maxc} characters, ending with a full stop or question mark.
  The narrator tells the story; characters speak their own words. People inside the story that
  Murugan tells are listed ONCE each in tale_cast (at most four): id (tale_1 ... tale_4), kind (boy,
  girl, woman, man, old_woman or old_man: it chooses their voice), an English name, and look: one
  English sentence fixing their age, hair and clothes for the whole episode (e.g. "Somu, a
  7-year-old Tamil village boy with curly hair, in a cream cotton shirt and white veshti"). Each
  speaks with their own id as speaker, and only their own words: what the narrator says about them
  is the narrator's line. In picture descriptions call them by name and do not re-describe them; in
  characters list their id. Every person a line mentions as present must be in that picture.

The lesson must rest on ONE line of Avvaiyar's Aathichoodi, chosen from the numbered list you are
given: return its number (source_number) and copy the line exactly (source_line_ta). A line that
is not in the list is rejected -- never write a line from memory. source_name_ta is "ஆத்திசூடி".
The story Murugan tells may be a well-known one about him (Avvaiyar and the fruit, the mango and
the journey round the world, teaching the meaning of Om) or a simple new tale; if it is a new
tale, do not present it as scripture.

Also return: title_ta and title_en; lesson_ta (one sentence); source_line_ta (the exact line),
source_name_ta (where it is from) and source_meaning_ta (its meaning in one simple sentence);
action_ta (one small thing to do today); question_ta (one question to talk about);
youtube_title (at most 90 characters, Tamil first then a short English part, honest, no hashtags);
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
youtube_title must say in Tamil that it is a story for children, in this shape:
"<the Aathichoodi line> | குழந்தைகளுக்கான குட்டி முருகன் கதை | Kids Moral Story".
Very simple words and short sentences. Warm and a little funny. Nothing frightening, no violence,
no punishment, nobody is shamed: the child is good and is learning. Kuzhali takes part in at least
two scenes. person_look: empty string.
Today's problem: {topic}."""

ADULTS = COMMON + """

THIS SERIES: "முருகன் சொன்ன வழி", for viewers from 15 to 80.
One person today, with an ordinary Tamil name and life (a student, a young mother, a shopkeeper, a
driver, a grandfather...), facing a problem of the world as it is now. Use speaker "person" for
them, and give person_look: one English sentence describing their appearance, so every picture
shows the same person. Start it with their name and exact age and say plainly that they are an
adult, with features a painter cannot mistake for a child (e.g. "Karthik, a 24-year-old grown man,
tall, with a short beard and moustache, ..."). Beside baby Murugan the person must still look
their age: Murugan is the only child in those pictures. person_look holds ONLY what never
changes (age, build, hair, face, clothes): no objects in the hand, no mood, no pose.
Anyone else who is in more than one picture (the person's child, wife, mother, a friend...) is also
listed in tale_cast with an id, kind, name and fixed look, and that id is in the scene's characters,
exactly like the people of Murugan's tale. The people of the tale and of the person's own life are
different people with different names.
This is a story for grown-ups, not a lesson with a story attached. Hold a viewer of 20 or of 70:
- Open in the middle of a moment with something at stake: a phone call that changes the day, a
  sentence said in anger, a result on a screen. No introductions.
- The person is intelligent and partly right. Their difficulty is real (money, time, pride, hurt,
  tiredness) and is never solved by one sentence of advice. Let them push back at Murugan,
  doubt him, even laugh at being advised by a child.
- Murugan is playful and sharp, never a preacher. He mostly asks questions, notices small things,
  teases gently, and lets the person find the answer. He never says "you should".
- The tale he tells has its own tension and a turn the viewer does not see coming; its people
  want things and make mistakes. Prefer a real incident from Tamil tradition (Avvaiyar, Murugan's
  own stories, Nakkeerar, Arunagirinathar, a king and a poet) told with fresh detail; if you
  invent one, give it specific people, a place and a surprise. No rich-man-poor-man fable.
- Show, don't tell: a look, a silence, an unanswered message says more than a sentence about
  feelings. Include one moment of gentle humour and one of real quiet.
- The ending changes one small thing and leaves the rest open. Life is not fixed in a day.
- The meaning is spoken ONCE, at the end, through the Aathichoodi line. Nobody explains the
  moral before that, and nobody repeats it after.
How they talk: natural spoken Tamil (பேச்சுத் தமிழ்) for the person, their family and Murugan, the
way people speak at home today; the narrator in simple clear Tamil, used sparingly (most scenes are
carried by what people say and do). Let lines breathe: short sentences, a comma where a speaker
pauses, three dots where a thought trails off, real questions that get real answers, and sometimes
no answer at all.
Shape, {smin}-{smax} scenes in all:
1. The moment (3-4 scenes): the viewer thinks "that is me".
2. Murugan turns up where nobody expects a god: on the bus seat, at the tea shop, on the office
   stairs (2-3 scenes). The person is not sure what to make of him.
3. The tale, with its turn (6-8 scenes).
4. Back to today: the person tries one small thing, and it is not easy (3-4 scenes).
5. The Aathichoodi line and its meaning in one sentence; one thing to try today; one question to
   carry (1-2 scenes).
No medical, legal or financial advice; no blaming of any group; nothing about caste.
Today's problem: {topic}."""

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

# a picture description that asks for writing, and a fixed look that carries a prop / mood / pose
_WRITING = re.compile(r"\b(written|writing|letters?|lettering|text|caption|title card|quote|quotation|inscri\w+|"
                      r"calligraph\w+|displaying the|showing the (line|words|verse))\b", re.I)
_PROP = re.compile(r"\b(holding|carrying|in (his|her) hand|phone|smartphone|laptop|looking|smiling|tired|sad|"
                   r"worried|sitting|standing)\b", re.I)
_TAMIL = re.compile(r"^[஀-௿\s.,;!?…‌‍-]+$")


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
    smin, smax = c.get(f"{series}_scenes") or (c["scenes_min"], c["scenes_max"])
    return template.format(channel=c["channel_name"], maxc=c["max_line_chars"], smin=smin, smax=smax, topic=topic)


def validate(data: dict, settings: dict) -> list[str]:
    c = settings["content"]
    errors = []
    scenes = data.get("scenes", [])
    smin, smax = c.get(f"{data.get('series', '')}_scenes") or (c["scenes_min"], c["scenes_max"])
    if not smin <= len(scenes) <= smax + 2:
        errors.append(f"need {smin}-{smax} scenes, got {len(scenes)}")
    spoken_lines = sum(len(sc.get("lines", [])) for sc in scenes)
    if scenes and spoken_lines < 2.8 * len(scenes):
        errors.append(f"too short: {spoken_lines} lines in {len(scenes)} scenes; give every scene 3-5 lines")
    if _PROP.search(data.get("person_look", "")):
        errors.append("person_look must hold only permanent features (age, build, hair, face, clothes): "
                      "remove objects in the hand, moods and poses")
    for i, sc in enumerate(scenes, 1):
        if _WRITING.search(sc.get("picture", "")):
            errors.append(f"scene {i}: a picture must not show writing, letters, a scroll or card with a line, "
                          "or a title (the captions show the words): describe a scene without any text")
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
    if not 10 <= len(data.get("youtube_title", "")) <= 100:
        errors.append("youtube_title must be 10-100 characters")
    ids = {t.get("id") for t in data.get("tale_cast", [])}
    used = {l.get("speaker") for sc in scenes for l in sc.get("lines", []) if str(l.get("speaker", "")).startswith("tale_")}
    if used - ids:
        errors.append(f"speakers {sorted(used - ids)} are not listed in tale_cast")
    return errors


def voice_for(speaker: str, tale_cast: list[dict] | None, voices: dict) -> dict:
    """The voice settings for a speaker: the cast's own, or for a person in the tale the voice of
    their kind, shifted a little by their id so two of a kind differ."""
    tale = {t.get("id"): t for t in tale_cast or []}
    if speaker in tale:
        style = dict(voices[TALE_KINDS.get(tale[speaker].get("kind"), "adult")])
        style["semitones"] = style["semitones"] + TALE_SHIFT.get(speaker, 0.0)
        return style
    return voices[CAST.get(speaker, {}).get("voice") or "narrator"]


def picture_prompt(scene: dict, person_look: str = "", tale_cast: list[dict] | None = None) -> str:
    """The full prompt for one scene: the moment, each visible character's fixed look, the style."""
    tale = {t.get("id") or t.get("role"): t["look"] for t in tale_cast or []}
    looks = []
    for who in scene.get("characters", []):
        look = person_look if who == "person" else tale.get(who) or CAST.get(who, {}).get("look", "")
        if look:
            looks.append(look)
    if not scene.get("characters"):
        # A scene of objects or scenery: a style text that speaks of faces and grown-ups paints people
        # into it (a lamp still life came back with a family behind it, three times).
        return f"{scene['picture'].strip()} {STYLE_SCENERY}"
    cast = " Characters: " + "; ".join(looks) + "." if looks else ""
    return f"{scene['picture'].strip()}{cast} {STYLE}"
