"""The picture people see before they click. Built the way thumbnails that get clicked are built:
  - faces with a strong feeling, large (the human moment of the story, close up);
  - baby Murugan beside it, in his own beautiful scene (nothing added around him);
  - very few, very large words on tilted colour plates (white on red, black on yellow), readable
    on a phone at a glance, plus one question that can only be answered by watching;
  - high contrast and saturation, darkened corners, a bright frame.
1280x720, under 2 MB.

Text is drawn by FFmpeg's subtitle renderer (libass), which shapes Tamil letters correctly."""
from __future__ import annotations

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


def make(out: Path, story: tuple[Path, tuple], murugan: tuple[Path, tuple], big: str, small: str, ffmpeg: Path) -> Path:
    """story / murugan: (picture, crop box as fractions). big: 2-5 words in two lines ("line one\\Nline two"):
    the first on a red plate, the second on a yellow one. small: one question on the bottom band."""
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
    for i in range(BAND):                                                            # the bottom band: deep red, darker lower down
        od.line([(0, top_h + i), (SIZE[0], top_h + i)], fill=(int(170 - 80 * i / BAND), 0, 0, 255))
    od.rectangle([0, top_h - 8, SIZE[0], top_h], fill=(255, 214, 40, 255))
    frame = 9
    od.rectangle([0, 0, SIZE[0] - 1, SIZE[1] - 1], outline=(255, 214, 40, 255), width=frame)   # a bright frame
    canvas = Image.alpha_composite(canvas.convert("RGBA"), over).convert("RGB")

    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    base = work / "thumbnail_base.png"
    canvas.save(base)
    first, _, second = big.partition("\\N")
    low = top_h - 40
    ass = work / "thumbnail.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SIZE[0]}
PlayResY: {SIZE[1]}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Red,Mukta Malar ExtraBold,92,&H00FFFFFF,&H00FFFFFF,&H001818D8,&H00000000,-1,0,0,0,100,100,0,0,3,14,7,7,0,0,0,1
Style: Yellow,Mukta Malar ExtraBold,112,&H00000000,&H00000000,&H0000E1FF,&H00000000,-1,0,0,0,100,100,0,0,3,14,7,7,0,0,0,1
Style: Small,Mukta Malar ExtraBold,68,&H0000F0FF,&H0000F0FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,3,2,20,20,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,Red,,0,0,0,,{{\\pos(34,{low - 268})\\frz4}}{first}
Dialogue: 1,0:00:00.00,0:00:10.00,Yellow,,0,0,0,,{{\\pos(34,{low - 138})\\frz4}}{second}
Dialogue: 2,0:00:00.00,0:00:10.00,Small,,0,0,0,,{small}
""", encoding="utf-8")
    fonts = (ROOT / "assets" / "fonts").relative_to(ROOT).as_posix()
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-loop", "1", "-t", "1", "-i", str(base.relative_to(ROOT)), "-vf",
                    f"ass={ass.relative_to(ROOT).as_posix()}:fontsdir={fonts}", "-frames:v", "1", "-q:v", "2",
                    str(out.relative_to(ROOT))], check=True, cwd=ROOT)
    return out
