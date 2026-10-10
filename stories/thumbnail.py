"""The picture people see before they click: the human moment of the story, close up, beside a
glowing baby Murugan, with a few very large Tamil words. 1280x720, under 2 MB.

Text is drawn by FFmpeg's subtitle renderer (libass), which shapes Tamil letters correctly."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from shorts.config import ROOT

SIZE = (1280, 720)
BAND = 124          # height of the bottom band
SPLIT = 740         # where the story picture ends at the top; the edge slants to SPLIT - 110 at the band


def _crop(path: Path, box: tuple[float, float, float, float], size: tuple[int, int]) -> Image.Image:
    """The part of the picture given as fractions (left, top, right, bottom), filled to `size`."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    part = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    scale = max(size[0] / part.width, size[1] / part.height)
    part = part.resize((round(part.width * scale), round(part.height * scale)), Image.LANCZOS)
    left, top = (part.width - size[0]) // 2, (part.height - size[1]) // 2
    return part.crop((left, top, left + size[0], top + size[1]))


def _rays(size: tuple[int, int], centre: tuple[int, int]) -> Image.Image:
    """A golden sunburst: bright at the centre, with soft rays, to sit behind Murugan."""
    w, h = size
    glow = Image.new("RGB", size, (150, 30, 0))
    draw = ImageDraw.Draw(glow)
    far = int(math.hypot(w, h))
    for k in range(0, 360, 12):
        a, b = math.radians(k), math.radians(k + 6)
        draw.polygon([centre, (centre[0] + far * math.cos(a), centre[1] + far * math.sin(a)),
                      (centre[0] + far * math.cos(b), centre[1] + far * math.sin(b))], fill=(235, 120, 0))
    glow = glow.filter(ImageFilter.GaussianBlur(5))
    halo = Image.new("L", size, 0)
    hd = ImageDraw.Draw(halo)
    for r in range(430, 0, -6):
        hd.ellipse([centre[0] - r, centre[1] - r, centre[0] + r, centre[1] + r], fill=int(255 * (1 - r / 430) ** 1.4))
    return Image.composite(Image.new("RGB", size, (255, 232, 120)), glow, halo)


def _cutout(path: Path, box: tuple[float, float, float, float], height: int) -> Image.Image:
    """Murugan lifted off his background: the part of his picture in `box`, with a soft-edged oval
    mask (a painted background has no clean outline to cut along)."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    part = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    part = part.resize((round(part.width * height / part.height), height), Image.LANCZOS)
    mask = Image.new("L", part.size, 0)
    ImageDraw.Draw(mask).ellipse([part.width * 0.13, part.height * 0.07, part.width * 0.87, part.height * 1.30], fill=255)
    part.putalpha(mask.filter(ImageFilter.GaussianBlur(part.width // 11)))
    return part


def make(out: Path, story: tuple[Path, tuple], murugan: tuple[Path, tuple], big: str, small: str, ffmpeg: Path) -> Path:
    """story / murugan: (picture, crop box as fractions). big: 2-5 words in two lines ("line one\\Nline two"),
    the first white and the second yellow. small: one question or promise on the bottom band."""
    top_h = SIZE[1] - BAND
    canvas = _rays(SIZE, (SPLIT + (SIZE[0] - SPLIT) // 2 - 20, top_h // 2 - 10))
    left = ImageEnhance.Contrast(ImageEnhance.Color(_crop(story[0], story[1], (SPLIT, top_h))).enhance(1.35)).enhance(1.12)
    edge = Image.new("L", (SPLIT, top_h), 0)
    ImageDraw.Draw(edge).polygon([(0, 0), (SPLIT, 0), (SPLIT - 110, top_h), (0, top_h)], fill=255)
    canvas.paste(left, (0, 0), edge)
    draw = ImageDraw.Draw(canvas)
    draw.line([(SPLIT, -4), (SPLIT - 110, top_h)], fill=(255, 255, 255), width=12)        # the slanted white edge
    child = _cutout(murugan[0], murugan[1], int(top_h * 1.12))
    child = ImageEnhance.Color(child).enhance(1.3)
    canvas.paste(child, (SPLIT - 55 + (SIZE[0] - SPLIT + 55 - child.width) // 2, top_h - child.height + 30), child)
    shade = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(300):                                    # darker towards the bottom, behind the big words
        sd.line([(0, top_h - 300 + y), (SPLIT - 110, top_h - 300 + y)], fill=(0, 0, 0, int(140 * (y / 300) ** 1.5)))
    sd.rectangle([0, top_h, SIZE[0], SIZE[1]], fill=(140, 0, 0, 255))
    sd.rectangle([0, top_h - 8, SIZE[0], top_h], fill=(255, 214, 40, 255))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shade).convert("RGB")
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    base = work / "thumbnail_base.png"
    canvas.save(base)
    first, _, second = big.partition("\\N")
    ass = work / "thumbnail.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SIZE[0]}
PlayResY: {SIZE[1]}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Big,Mukta Malar ExtraBold,118,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,0,0,1,10,5,1,24,20,{BAND + 18},1
Style: Small,Mukta Malar ExtraBold,66,&H0030E6FF,&H0030E6FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,20,20,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,Big,,0,0,0,,{first}\\N{{\\c&H1EDCFF&}}{second}
Dialogue: 0,0:00:00.00,0:00:10.00,Small,,0,0,0,,{small}
""", encoding="utf-8")
    fonts = (ROOT / "assets" / "fonts").relative_to(ROOT).as_posix()
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-loop", "1", "-t", "1", "-i", str(base.relative_to(ROOT)), "-vf",
                    f"ass={ass.relative_to(ROOT).as_posix()}:fontsdir={fonts}", "-frames:v", "1", "-q:v", "2",
                    str(out.relative_to(ROOT))], check=True, cwd=ROOT)
    return out
