"""Visuals stage: prepares each still image once (cover-fit to 9:16 with motion headroom,
then every bake-time effect) and caches it; then yields the video's frames with sub-pixel
Ken Burns motion and transitions at sentence boundaries.

Motion uses OpenCV warpAffine (bilinear): benchmarked on this laptop against ffmpeg
zoompan and Pillow for 900 frames of 1080x1920 -- 30 s wall / 123 s CPU with no visible
shudder, vs 104 s / 146 s with visible shudder for zoompan (see REDESIGN_PLAN.md)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from shorts.cache import Cache
from shorts.effects import Effect

HEADROOM = 1.12  # baked image is 12% larger than the frame so zoom/pan never shows an edge
BAKE_VERSION = "1"


@dataclass
class Segment:
    image: np.ndarray  # baked uint8 RGB, HEADROOM x frame size
    start: float
    end: float
    zoom_from: float
    zoom_to: float
    pan: tuple[float, float]  # fraction of the headroom margin to drift across (x, y)
    loop: bool = False  # go there and back, so the last frame matches the first (seamless replay)
    video: object = None  # optional talking.FrameSource: animated frames replace the still picture


def bake_image(src: Path, cfg: dict, effects: list[Effect], cache: Cache) -> np.ndarray:
    W, H = cfg["video"]["width"], cfg["video"]["height"]
    bake_cfg = {e.name: e.cfg for e in effects if e.has_bake}
    # How much larger than the frame the picture is kept, i.e. how far the camera is zoomed in at
    # rest. Shorts use 12%; wide story pictures are composed for the frame and use much less.
    headroom = float(cfg["effects"]["kenburns"].get("headroom", HEADROOM))
    if headroom != HEADROOM:
        bake_cfg = {**bake_cfg, "_headroom": headroom}
    key = cache.key("bake", BAKE_VERSION, src, W, H, bake_cfg)
    path, hit = cache.lookup("bake", key, ".png")
    if hit:
        return cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)

    img = cv2.imdecode(np.fromfile(str(src), np.uint8), cv2.IMREAD_COLOR)  # fromfile: non-ASCII paths
    if img is None:
        raise ValueError(f"Can't read image: {src}")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    MW, MH = round(W * headroom), round(H * headroom)
    scale = max(MW / img.shape[1], MH / img.shape[0])
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
    img = cv2.resize(img, (round(img.shape[1] * scale), round(img.shape[0] * scale)), interpolation=interp)
    top, left = (img.shape[0] - MH) // 2, (img.shape[1] - MW) // 2
    img = img[top:top + MH, left:left + MW]

    f = img.astype(np.float32) / 255
    for e in effects:
        if e.has_bake:
            f = e.bake(f)
    out = (np.clip(f, 0, 1) * 255 + 0.5).astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(out, cv2.COLOR_RGB2BGR))
    return out


def plan_segments(images: list[np.ndarray], line_spans: list[tuple[float, float]], duration: float,
                  kb_cfg: dict, seed: int) -> list[Segment]:
    """One segment per image. With several images, cuts land on sentence boundaries
    (between spoken lines), spread as evenly as possible across the lines."""
    rng = np.random.default_rng(seed)
    k = len(images)
    if k == 1 or len(line_spans) < 2:
        bounds = [0.0, duration]
    else:
        k = min(k, len(line_spans))
        per = len(line_spans) / k
        cut_lines = [round(per * i) for i in range(1, k)]
        cuts = [(line_spans[j - 1][1] + line_spans[j][0]) / 2 for j in cut_lines]
        bounds = [0.0, *cuts, duration]

    zoom = kb_cfg.get("zoom", 0.08) if kb_cfg.get("enabled", True) else 0.0
    pan = kb_cfg.get("pan", 0.03) if kb_cfg.get("enabled", True) else 0.0
    segments = []
    for i in range(len(bounds) - 1):
        zoom_in = (i % 2 == 0) if rng.random() < 0.8 else (i % 2 == 1)  # mostly alternate in/out
        z0, z1 = (1.0, 1.0 + zoom) if zoom_in else (1.0 + zoom, 1.0)
        direction = rng.uniform(-1, 1, 2) * (pan / max(HEADROOM - 1, 1e-6))
        segments.append(Segment(images[i], bounds[i], bounds[i + 1], z0, z1, (float(direction[0]), float(direction[1]))))
    # Seamless loop (Shorts replay automatically, and replays count): with one image the
    # motion returns to where it started, so the jump from the last frame to the first is invisible.
    if kb_cfg.get("loop", False) and len(segments) == 1:
        segments[0].loop = True
    return segments


def _ease(p: float) -> float:
    return p * p * (3 - 2 * p)  # smoothstep: motion starts and ends gently


def _warp(seg: Segment, t: float, W: int, H: int) -> np.ndarray:
    span = max(seg.end - seg.start, 1e-6)
    raw = min(max((t - seg.start) / span, 0.0), 1.0)
    p = 0.5 - 0.5 * np.cos(2 * np.pi * raw) if seg.loop else _ease(raw)  # loop: 0 -> 1 -> 0, smooth at both ends
    z = seg.zoom_from + (seg.zoom_to - seg.zoom_from) * p
    image = seg.image
    if seg.video is not None:
        frame = seg.video.at(t)
        if frame is not None:
            image = frame
    MH, MW = image.shape[:2]
    zf = z * W / MW
    margin_x = (MW * zf - W) / 2 / zf  # how far (in source px) the view can drift at this zoom
    margin_y = (MH * zf - H) / 2 / zf
    cx = MW / 2 + seg.pan[0] * margin_x * (p - 0.5) * 2
    cy = MH / 2 + seg.pan[1] * margin_y * (p - 0.5) * 2
    m = np.float32([[zf, 0, W / 2 - cx * zf], [0, zf, H / 2 - cy * zf]])
    return cv2.warpAffine(image, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def frames(segments: list[Segment], W: int, H: int, fps: int, duration: float, transition: dict):
    """Yields (t, uint8 RGB frame). Transitions blend the two neighbouring segments'
    motion only during the transition window, so they cost extra only for ~20 frames."""
    n = int(round(duration * fps))
    td = transition.get("duration_s", 0.8) if transition.get("enabled", True) and len(segments) > 1 else 0.0
    style = transition.get("style", "crossfade")
    for i in range(n):
        t = i / fps
        idx = next((k for k, s in enumerate(segments) if t < s.end), len(segments) - 1)
        seg = segments[idx]
        frame = _warp(seg, t, W, H)
        if td and idx + 1 < len(segments) and t > seg.end - td / 2:
            nxt = segments[idx + 1]
            a = (t - (seg.end - td / 2)) / td
            frame = _blend(frame, _warp(nxt, t, W, H), a, style, W, H)
        elif td and idx > 0 and t < seg.start + td / 2:
            prev = segments[idx - 1]
            a = 0.5 + (t - seg.start) / td
            frame = _blend(_warp(prev, t, W, H), frame, a, style, W, H)
        yield t, frame


def _blend(a_img: np.ndarray, b_img: np.ndarray, a: float, style: str, W: int, H: int) -> np.ndarray:
    a = _ease(min(max(a, 0.0), 1.0))
    if style == "slide":
        off = int(round(W * a))
        out = np.empty_like(a_img)
        out[:, :W - off] = a_img[:, off:]
        out[:, W - off:] = b_img[:, :off]
        return out
    if style == "zoom":
        s = 1 + 0.15 * a
        m = np.float32([[s, 0, W / 2 * (1 - s)], [0, s, H / 2 * (1 - s)]])
        a_img = cv2.warpAffine(a_img, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.addWeighted(a_img, 1 - a, b_img, a, 0)
