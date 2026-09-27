"""Per-frame effects. Both are deliberately cheap: particles touch only small sprite-sized
patches (~70 patches of <40x40 px, not the whole 1080x1920 frame), and the vignette is
one precomputed mask applied with a single multithreaded OpenCV multiply."""
from __future__ import annotations

import cv2
import numpy as np

from shorts.effects import Effect, RenderContext, effect

_GOLD = np.array([255, 214, 140], np.float32)


def _glow_sprite(radius: int, star: bool) -> np.ndarray:
    size = radius * 4 + 1
    yy, xx = np.mgrid[-2 * radius:2 * radius + 1, -2 * radius:2 * radius + 1].astype(np.float32)
    d2 = xx ** 2 + yy ** 2
    glow = np.exp(-d2 / (2 * (radius * 0.9) ** 2)) * 0.8 + np.exp(-d2 / (2 * (radius * 0.25) ** 2))
    if star:  # thin 4-point twinkle rays
        rays = np.exp(-(xx ** 2) / 1.2) * np.exp(-(yy ** 2) / (2 * (radius * 1.6) ** 2))
        rays += np.exp(-(yy ** 2) / 1.2) * np.exp(-(xx ** 2) / (2 * (radius * 1.6) ** 2))
        glow += rays * 0.7
    glow = np.clip(glow, 0, 1)
    return (glow[..., None] * _GOLD).reshape(size, size, 3)


@effect("particles")
class Particles(Effect):
    """Golden sparkles and slow-rising light dust, generated procedurally with a fixed seed
    (identical on every re-render). If `overlay` is set in config, the render stage
    screen-blends that video instead and this effect is skipped."""
    has_frame = True

    def prepare(self, ctx: RenderContext):
        if self.cfg.get("overlay"):
            self.n = 0
            return
        rng = np.random.default_rng(ctx.seed)
        n = int(self.cfg.get("count", 70))
        self.n, self.w, self.h = n, ctx.width, ctx.height
        self.x0 = rng.uniform(0, ctx.width, n)
        self.y0 = rng.uniform(0, ctx.height, n)
        self.vx = rng.normal(0, 6, n)
        self.vy = -rng.uniform(8, 45, n)  # drift upward, like lamp embers / light dust
        self.radius = rng.choice([2, 3, 3, 4, 5, 6, 8], n)
        self.star = rng.random(n) < 0.18
        self.freq = rng.uniform(0.3, 1.2, n)
        self.phase = rng.uniform(0, 2 * np.pi, n)
        self.base = rng.uniform(0.35, 1.0, n) * float(self.cfg.get("opacity", 0.85))
        self.sprites = {(r, s): _glow_sprite(int(r), bool(s)) for r, s in set(zip(self.radius, self.star))}

    def frame(self, rgb, t):
        if not self.n:
            return
        x = (self.x0 + self.vx * t) % self.w
        y = (self.y0 + self.vy * t) % self.h
        alpha = self.base * (0.55 + 0.45 * np.sin(2 * np.pi * self.freq * t + self.phase))
        H, W = rgb.shape[:2]
        for i in range(self.n):
            sprite = self.sprites[(self.radius[i], self.star[i])]
            half = sprite.shape[0] // 2
            cx, cy = int(x[i]), int(y[i])
            x0, y0, x1, y1 = cx - half, cy - half, cx + half + 1, cy + half + 1
            sx0, sy0 = max(0, -x0), max(0, -y0)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
            if x0 >= x1 or y0 >= y1:
                continue
            patch = sprite[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)] * alpha[i]
            roi = rgb[y0:y1, x0:x1]
            cv2.add(roi, patch.astype(np.uint8), dst=roi)  # additive light, saturating at 255


@effect("glow_pulse")
class GlowPulse(Effect):
    """A soft warm light that slowly 'breathes' around the subject (divine-presence feel).
    The glow is precomputed once; each frame is one scalar multiply + one saturating add."""
    has_frame = True

    def prepare(self, ctx: RenderContext):
        cx, cy = self.cfg.get("center", [0.5, 0.42])
        radius = float(self.cfg.get("radius", 0.38)) * ctx.width
        yy, xx = np.mgrid[0:ctx.height, 0:ctx.width].astype(np.float32)
        d2 = (xx - cx * ctx.width) ** 2 + (yy - cy * ctx.height) ** 2
        glow = np.exp(-d2 / (2 * radius ** 2))[..., None] * _GOLD * float(self.cfg.get("strength", 0.22))
        self.glow = np.clip(glow, 0, 255).astype(np.uint8)
        self.period = float(self.cfg.get("period_s", 4.0))
        self.buf = np.empty_like(self.glow)

    def frame(self, rgb, t):
        k = 0.5 - 0.5 * np.cos(2 * np.pi * t / self.period)  # 0..1, smooth
        # convertScaleAbs scales every channel (cv2.multiply by a plain number would scale only the first)
        cv2.convertScaleAbs(self.glow, dst=self.buf, alpha=k)
        cv2.add(rgb, self.buf, dst=rgb)


@effect("vignette")
class Vignette(Effect):
    """Darkens the corners to pull the eye to the centre. Screen-fixed (doesn't move with
    the Ken Burns motion), so it's one precomputed mask."""
    has_frame = True

    def prepare(self, ctx: RenderContext):
        yy, xx = np.mgrid[0:ctx.height, 0:ctx.width].astype(np.float32)
        nx, ny = (xx / ctx.width - 0.5) * 2, (yy / ctx.height - 0.5) * 2
        d = np.sqrt(nx ** 2 * 0.9 + ny ** 2 * 0.6)
        mask = 1 - float(self.cfg.get("strength", 0.35)) * np.clip(d - 0.35, 0, None) ** 1.6
        self.mask = np.repeat((np.clip(mask, 0, 1) * 255).astype(np.uint8)[..., None], 3, axis=2)

    def frame(self, rgb, t):
        cv2.multiply(rgb, self.mask, dst=rgb, scale=1 / 255)
