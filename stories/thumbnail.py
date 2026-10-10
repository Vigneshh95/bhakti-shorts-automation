"""The picture people see before they click, made automatically for every story.

Built the way thumbnails that get clicked are built:
  - faces with a strong feeling, large (the human moment of the story, close up);
  - baby Murugan beside it with his vel, in his own beautiful scene (nothing added around him);
  - very few, very large words on tilted colour plates (white on red, black on yellow), readable
    on a phone at a glance;
  - one question on a bright band that can only be answered by watching;
  - high contrast and saturation, darkened corners, a bright frame.
1280x720, under 2 MB.

design(): Gemini looks at the story's pictures and chooses the two pictures, where to crop them,
and the words. make(): draws it. for_story(): both, kept in script.json so a re-run draws the same.
Text is drawn by FFmpeg's subtitle renderer (libass), which shapes Tamil letters correctly."""
from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from shorts.config import ROOT
from shorts.log import log

SIZE = (1280, 720)
BAND = 136          # height of the bottom band
SPLIT = 740         # where the story picture ends at the top; the edge slants to SPLIT - 110 at the band
LINE_CHARS = (16, 14)   # most letters on the red and the yellow plate (longer text is drawn smaller)
QUESTION_CHARS = 38

DESIGN_SYSTEM = """You design YouTube thumbnails for an illustrated Tamil story series in which baby Lord
Murugan helps ordinary people. You are shown the numbered pictures of one story and its script.
Choose what makes a viewer stop and click:
- story_scene: the picture with the strongest HUMAN feeling of today's story (shock, hurt, tears,
  anger, longing) on clearly visible faces. Never a picture with Murugan, never one without people.
- story_box: the part of that picture to show, as fractions of its width and height (left, top,
  right, bottom): close on the faces so they are large, keeping the whole of each face.
- murugan_scene: the picture in which baby Murugan looks most beautiful and is clearly holding or
  standing with his vel (spear), in a lovely setting. The vel must be visible.
- murugan_box: the part to show: his face, crown and upper body with the vel, and some of the scene.
- line1 and line2: the hook, in Tamil. Two short phrases that go together and make the viewer feel
  the story's moment (what was said, what happened, what it cost), e.g. "ஒரே வார்த்தை…" /
  "வீடே மௌனம்!". Everyday words, strong feeling, no names, nothing false or exaggerated beyond the
  story. line1 at most {l1} letters, line2 at most {l2} letters, counting spaces.
- question: one Tamil question about what Murugan does or asks in the story, which can only be
  answered by watching, e.g. "முருகன் கேட்ட அந்த ஒரு கேள்வி என்ன?". At most {q} letters. It must not
  give the answer away.
Tamil script only in the three texts: no English letters, digits, emoji or quotation marks."""
DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "story_scene": {"type": "integer"}, "story_box": {"type": "array", "items": {"type": "number"}},
        "murugan_scene": {"type": "integer"}, "murugan_box": {"type": "array", "items": {"type": "number"}},
        "line1": {"type": "string"}, "line2": {"type": "string"}, "question": {"type": "string"}},
    "required": ["story_scene", "story_box", "murugan_scene", "murugan_box", "line1", "line2", "question"],
    "additionalProperties": False,
}
_TAMIL = re.compile(r"^[஀-௿\s.,;!?…-]+$")


def _box(values, min_w: float, min_h: float) -> tuple[float, float, float, float]:
    """A usable crop box from the model's numbers: in range, the right way round, not too small."""
    v = [min(1.0, max(0.0, float(x))) for x in (list(values) + [0, 0, 1, 1])[:4]]
    left, top, right, bottom = min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3])
    for size, lo_hi in ((min_w, "x"), (min_h, "y")):
        a, b = (left, right) if lo_hi == "x" else (top, bottom)
        if b - a < size:                       # grow around the centre, staying inside the picture
            c = (a + b) / 2
            a, b = max(0.0, c - size / 2), min(1.0, c + size / 2)
            a, b = (max(0.0, b - size), b) if b == 1.0 else (a, min(1.0, a + size))
        left, right, top, bottom = (a, b, top, bottom) if lo_hi == "x" else (left, right, a, b)
    return left, top, right, bottom


def check(design: dict, script: dict) -> list[str]:
    """What is wrong with a design (empty = usable)."""
    problems, scenes = [], script["scenes"]
    for key in ("story_scene", "murugan_scene"):
        if not 1 <= int(design.get(key, 0)) <= len(scenes):
            problems.append(f"{key} must be a picture number from 1 to {len(scenes)}")
    if not problems:
        if "murugan" in scenes[design["story_scene"] - 1]["characters"]:
            problems.append("story_scene must be a picture WITHOUT Murugan (the human moment)")
        if "murugan" not in scenes[design["murugan_scene"] - 1]["characters"]:
            problems.append("murugan_scene must be a picture with baby Murugan in it")
    for key, limit in (("line1", LINE_CHARS[0]), ("line2", LINE_CHARS[1]), ("question", QUESTION_CHARS)):
        text = design.get(key, "").strip()
        if not text or not _TAMIL.match(text):
            problems.append(f"{key} must be Tamil script only")
        elif len(text) > limit:
            problems.append(f"{key} is {len(text)} letters; at most {limit}")
    return problems


def design(script: dict, pictures: list[Path], ask) -> dict:
    """ask: (system, user, schema, images) -> dict. Returns a checked design."""
    images = []
    for i, p in enumerate(pictures, 1):
        buf = io.BytesIO()
        Image.open(p).convert("RGB").resize((448, 256)).save(buf, "JPEG", quality=80)
        images.append((f"picture {i}", buf.getvalue()))
    listing = "\n".join(f"picture {i}: {sc['picture']}\n" + "\n".join(f"   {l['text']}" for l in sc["lines"])
                        for i, sc in enumerate(script["scenes"], 1))
    system = DESIGN_SYSTEM.format(l1=LINE_CHARS[0], l2=LINE_CHARS[1], q=QUESTION_CHARS)
    user, problems = f"Story: {script['title_ta']} ({script.get('title_en', '')})\n\n{listing}", []
    for _ in range(3):
        d = ask(system, user + ("\n\nYour last answer had these problems, fix them:\n- " + "\n- ".join(problems) if problems else ""),
                DESIGN_SCHEMA, images)
        problems = check(d, script)
        if not problems:
            # The model draws its boxes tight around the faces. Room is added so that nothing is cut:
            # to the right of the story picture (the slanted edge hides its lower right corner), and
            # above and beside Murugan (the tip of his vel and his crown must be whole).
            s, m = d["story_box"], d["murugan_box"]
            d["story_box"] = list(_box([s[0] - 0.06, s[1] - 0.04, s[2] + 0.16, s[3] + 0.12], 0.6, 0.7))
            d["murugan_box"] = list(_box([m[0] - 0.08, m[1] - 0.10, m[2] + 0.05, m[3]], 0.42, 0.68))
            return d
        log.warning("  thumbnail design rejected: %s", "; ".join(problems)[:200])
    raise RuntimeError("no usable thumbnail design: " + "; ".join(problems))


def for_story(folder: Path, script: dict, pictures: list[Path], ask, ffmpeg: Path) -> Path:
    """The story's thumbnail (<folder>/thumbnail.jpg). The design is kept in script.json ("thumbnail"):
    change its words or boxes there by hand and run again to redraw."""
    if not script.get("thumbnail"):
        script["thumbnail"] = design(script, pictures, ask)
        (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
    d = script["thumbnail"]
    return make(folder / "thumbnail.jpg", (pictures[d["story_scene"] - 1], tuple(d["story_box"])),
                (pictures[d["murugan_scene"] - 1], tuple(d["murugan_box"])), d["line1"], d["line2"], d["question"], ffmpeg)


def _crop(path: Path, box: tuple[float, float, float, float], size: tuple[int, int]) -> Image.Image:
    """The part of the picture given as fractions (left, top, right, bottom), filled to `size`."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    part = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    scale = max(size[0] / part.width, size[1] / part.height)
    part = part.resize((round(part.width * scale), round(part.height * scale)), Image.LANCZOS)
    left, top = (part.width - size[0]) // 2, (part.height - size[1]) // 5   # what is trimmed comes mostly off the bottom: heads stay
    return part.crop((left, top, left + size[0], top + size[1]))


def _finish(im: Image.Image) -> Image.Image:
    """Punch: sharper, darker corners, a fine grain so flat areas don't look plastic."""
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=2))
    w, h = im.size
    corners = Image.new("L", (w // 8, h // 8), 0)
    cd = ImageDraw.Draw(corners)
    for i in range(40):
        f = i / 40
        cd.ellipse([-w / 8 * 0.25 * (1 - f) + w / 16 * f * 0.2, -h / 8 * 0.25 * (1 - f) + h / 16 * f * 0.2,
                    w / 8 * (1.25 - 0.25 * f) - w / 16 * f * 0.2, h / 8 * (1.25 - 0.25 * f) - h / 16 * f * 0.2], fill=int(255 * f ** 0.5))
    corners = corners.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    im = Image.composite(im, ImageEnhance.Brightness(im).enhance(0.45), corners)
    grain = Image.effect_noise((w, h), 14).convert("RGB")
    return Image.blend(im, grain, 0.045)


def _fit(text: str, size: int, comfortable: int) -> int:
    """The font size for a line: full size up to `comfortable` letters, smaller for longer lines."""
    return size if len(text) <= comfortable else max(int(size * 0.6), int(size * comfortable / len(text)))


def make(out: Path, story: tuple[Path, tuple], murugan: tuple[Path, tuple], line1: str, line2: str, question: str,
         ffmpeg: Path) -> Path:
    """story / murugan: (picture, crop box as fractions). line1 on a red plate, line2 on a yellow one,
    the question on the bright bottom band."""
    top_h = SIZE[1] - BAND
    # Murugan in his own scene (a temple at dusk, a garden...): no added rays, sparkles or symbols.
    canvas = Image.new("RGB", SIZE, "black")
    right_w = SIZE[0] - SPLIT + 110
    right = ImageEnhance.Contrast(ImageEnhance.Color(_crop(murugan[0], murugan[1], (right_w, top_h))).enhance(1.3)).enhance(1.08)
    canvas.paste(right, (SPLIT - 110, 0))
    left = ImageEnhance.Contrast(ImageEnhance.Color(_crop(story[0], story[1], (SPLIT, top_h))).enhance(1.45)).enhance(1.18)
    edge = Image.new("L", (SPLIT, top_h), 0)
    ImageDraw.Draw(edge).polygon([(0, 0), (SPLIT, 0), (SPLIT - 110, top_h), (0, top_h)], fill=255)
    canvas.paste(left, (0, 0), edge)
    draw = ImageDraw.Draw(canvas)
    draw.line([(SPLIT + 3, -4), (SPLIT - 107, top_h)], fill=(255, 214, 40), width=20)   # the slanted edge: gold, then white
    draw.line([(SPLIT, -4), (SPLIT - 110, top_h)], fill=(255, 255, 255), width=10)
    canvas = _finish(canvas)

    over = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for i in range(BAND):                           # the bottom band: bright yellow, a little deeper lower down
        od.line([(0, top_h + i), (SIZE[0], top_h + i)], fill=(255, int(232 - 44 * i / BAND), int(40 - 40 * i / BAND), 255))
    od.rectangle([0, top_h - 10, SIZE[0], top_h], fill=(150, 0, 0, 255))                 # a dark red line above it
    od.rectangle([0, 0, SIZE[0] - 1, SIZE[1] - 1], outline=(150, 0, 0, 255), width=9)    # the frame
    canvas = Image.alpha_composite(canvas.convert("RGBA"), over).convert("RGB")

    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    base = work / "thumbnail_base.png"
    canvas.save(base)
    red, yellow = _fit(line1, 80, 13), _fit(line2, 96, 11)
    ask_size = _fit(question, 86, 34)
    y2 = top_h - 44 - int(yellow * 1.42)            # the yellow plate sits just above the band; the red one above it
    y1 = y2 - int(red * 1.42) - 14
    ass = work / "thumbnail.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SIZE[0]}
PlayResY: {SIZE[1]}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Red,Mukta Malar ExtraBold,{red},&H00FFFFFF,&H00FFFFFF,&H001010D0,&H00000000,-1,0,0,0,100,100,0,0,3,7,5,7,0,0,0,1
Style: Yellow,Mukta Malar ExtraBold,{yellow},&H00000000,&H00000000,&H0000E6FF,&H00000000,-1,0,0,0,100,100,0,0,3,7,5,7,0,0,0,1
Style: Ask,Mukta Malar ExtraBold,{ask_size},&H00000070,&H00000070,&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,Red,,0,0,0,,{{\\pos(30,{y1})\\frz3}}{line1}
Dialogue: 1,0:00:00.00,0:00:10.00,Yellow,,0,0,0,,{{\\pos(30,{y2})\\frz3}}{line2}
Dialogue: 2,0:00:00.00,0:00:10.00,Ask,,0,0,0,,{{\\pos({SIZE[0] // 2},{top_h + BAND // 2 - 2})}}{question}
""", encoding="utf-8")
    fonts = (ROOT / "assets" / "fonts").relative_to(ROOT).as_posix()
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-loop", "1", "-t", "1", "-i", str(base.relative_to(ROOT)), "-vf",
                    f"ass={ass.relative_to(ROOT).as_posix()}:fontsdir={fonts}", "-frames:v", "1", "-q:v", "2",
                    str(out.relative_to(ROOT))], check=True, cwd=ROOT)
    return out
