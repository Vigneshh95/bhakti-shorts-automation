"""The picture people see before they click: two moments of the story side by side (the human
moment and baby Murugan), a few very large Tamil words, strong colour. 1280x720, under 2 MB.

Text is drawn by FFmpeg's subtitle renderer (libass), which shapes Tamil letters correctly."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from shorts.config import ROOT

SIZE = (1280, 720)


def _crop(path: Path, box: tuple[float, float, float, float], size: tuple[int, int]) -> Image.Image:
    """The part of the picture given as fractions (left, top, right, bottom), filled to `size`."""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    part = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    scale = max(size[0] / part.width, size[1] / part.height)
    part = part.resize((round(part.width * scale), round(part.height * scale)), Image.LANCZOS)
    left, top = (part.width - size[0]) // 2, (part.height - size[1]) // 2
    return part.crop((left, top, left + size[0], top + size[1]))


def make(out: Path, left: tuple[Path, tuple], right: tuple[Path, tuple], big: str, small: str, ffmpeg: Path) -> Path:
    """left/right: (picture, crop box). big: 2-4 words, huge, bottom left (over clothes, never over a face). small: one line on the bottom band."""
    canvas = Image.new("RGB", SIZE, "black")
    split = 690
    canvas.paste(_crop(left[0], left[1], (split, SIZE[1])), (0, 0))
    canvas.paste(_crop(right[0], right[1], (SIZE[0] - split, SIZE[1])), (split, 0))
    canvas = ImageEnhance.Color(canvas).enhance(1.25)
    canvas = ImageEnhance.Contrast(canvas).enhance(1.08)
    shade = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shade)
    draw.rectangle([0, SIZE[1] - 112, SIZE[0], SIZE[1]], fill=(120, 10, 10, 235))      # bottom band
    draw.rectangle([0, SIZE[1] - 118, SIZE[0], SIZE[1] - 112], fill=(255, 205, 40, 255))
    draw.rectangle([split - 4, 0, split + 4, SIZE[1] - 118], fill=(255, 255, 255, 255))  # the divider
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shade).convert("RGB")
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    base = work / "thumbnail_base.png"
    canvas.save(base)
    ass = work / "thumbnail.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SIZE[0]}
PlayResY: {SIZE[1]}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Big,Mukta Malar ExtraBold,100,&H0030E6FF,&H0030E6FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,9,4,1,26,20,132,1
Style: Small,Mukta Malar ExtraBold,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,20,20,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,Big,,0,0,0,,{big}
Dialogue: 0,0:00:00.00,0:00:10.00,Small,,0,0,0,,{small}
""", encoding="utf-8")
    fonts = (ROOT / "assets" / "fonts").relative_to(ROOT).as_posix()
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-loop", "1", "-t", "1", "-i", str(base.relative_to(ROOT)), "-vf",
                    f"ass={ass.relative_to(ROOT).as_posix()}:fontsdir={fonts}", "-frames:v", "1", "-q:v", "2",
                    str(out.relative_to(ROOT))], check=True, cwd=ROOT)
    return out
