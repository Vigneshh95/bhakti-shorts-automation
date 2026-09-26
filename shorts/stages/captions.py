"""Captions stage: writes one .ass subtitle file holding every text element of the video --
word-highlighted captions, the hook title, the outro call-to-action and the watermark.
libass draws all of it inside the single render pass (with HarfBuzz shaping, so Tamil
vowel signs and conjuncts render correctly), which costs almost nothing per frame."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shorts.stages.audio import TimedWord

_BREAK_AFTER = (".", "!", "?", ";", ",", "।", ":")


@dataclass
class Chunk:
    words: list[TimedWord]

    @property
    def start(self) -> float:
        return self.words[0].start


def ass_color(hex_rgb: str, opacity: float = 1.0) -> str:
    """#RRGGBB + opacity -> ASS &HAABBGGRR (ASS alpha is inverted: 00 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    alpha = round((1 - opacity) * 255)
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ts(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def chunk_words(words: list[TimedWord], per_chunk: int) -> list[Chunk]:
    """Short phrases (default 3 words) read better on a phone than whole sentences.
    A chunk never spans two spoken lines and breaks early after punctuation."""
    chunks, current = [], []
    for i, w in enumerate(words):
        if current and (w.line != current[-1].line or len(current) >= per_chunk):
            chunks.append(Chunk(current))
            current = []
        current.append(w)
        if w.text.endswith(_BREAK_AFTER):
            chunks.append(Chunk(current))
            current = []
    if current:
        chunks.append(Chunk(current))
    return chunks


def build_ass(words: list[TimedWord], duration: float, cfg: dict, hook_text: str) -> str:
    W, H = cfg["video"]["width"], cfg["video"]["height"]
    cap, fx = cfg["captions"], cfg["effects"]
    font = cap["font"]
    y = round(H * cap["position_y"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{cap['size']},{ass_color(cap['color'])},&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,{cap['outline']},3,5,60,60,0,1
Style: Hook,{font},{round(cap['size'] * 1.05)},&H0000E6FF,&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,6,4,5,60,60,0,1
Style: Outro,{font},{round(cap['size'] * 0.72)},&H00FFFFFF,&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,5,3,5,60,60,0,1
Style: Mark,{font},{round(cap['size'] * 0.6)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    if cap["enabled"] and words:
        hi_text, hi_box = ass_color(cap["highlight_text"]), ass_color(cap["highlight_box"])
        chunks = chunk_words(words, cap["words_per_caption"])
        for ci, chunk in enumerate(chunks):
            chunk_end = chunks[ci + 1].start if ci + 1 < len(chunks) else min(duration, chunk.words[-1].end + 0.6)
            for wi, word in enumerate(chunk.words):
                seg_start = word.start if wi else chunk.start
                seg_end = chunk.words[wi + 1].start if wi + 1 < len(chunk.words) else chunk_end
                parts = []
                for wj, other in enumerate(chunk.words):
                    text = escape(other.text)
                    if wj == wi:
                        parts.append(f"{{\\1c{hi_text}\\3c{hi_box}\\bord{cap['outline'] + 9}\\shad0}}{text}{{\\r}}")
                    else:
                        parts.append(text)
                pop = "\\fscx88\\fscy88\\t(0,110,\\fscx100\\fscy100)\\fad(90,0)" if wi == 0 else ""
                events.append(f"Dialogue: 1,{ts(seg_start)},{ts(seg_end)},Caption,,0,0,0,,"
                              f"{{\\an5\\pos({W // 2},{y}){pop}}}{' '.join(parts)}")

    hook = fx["hook"]
    if hook["enabled"] and hook_text:
        d = hook["duration_s"]
        events.append(f"Dialogue: 2,{ts(0.05)},{ts(d)},Hook,,0,0,0,,"
                      f"{{\\an5\\pos({W // 2},{round(H * 0.16)})\\fad(250,350)\\fscx80\\fscy80\\t(0,300,\\fscx100\\fscy100)}}"
                      f"{escape(hook_text)}")

    outro = fx["outro"]
    if outro["enabled"] and outro["text"]:
        d = outro["duration_s"]
        events.append(f"Dialogue: 2,{ts(max(0, duration - d))},{ts(duration)},Outro,,0,0,0,,"
                      f"{{\\an5\\pos({W // 2},{round(H * 0.16)})\\fad(300,200)}}{escape(outro['text'])}")

    mark = fx["watermark"]
    if mark["enabled"] and mark["lines"]:
        alpha = f"&H{round((1 - mark['opacity']) * 255):02X}&"
        text = "\\N".join(escape(t) for t in mark["lines"])
        events.append(f"Dialogue: 0,{ts(0)},{ts(duration)},Mark,,0,0,0,,"
                      f"{{\\an5\\pos({W // 2},{round(H * mark['position_y'])})\\alpha{alpha}}}{text}")

    return header + "\n".join(events) + "\n"


def write_ass(path: Path, *args, **kwargs) -> Path:
    path.write_text(build_ass(*args, **kwargs), encoding="utf-8-sig")
    return path
