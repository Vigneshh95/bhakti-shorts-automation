"""Bake-time effects: applied once to each still image and cached, so they cost nothing
per frame no matter how long the video is."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from shorts.effects import Effect, effect


@effect("grade")
class Grade(Effect):
    """Consistent warm devotional look. Uses a .cube LUT if one is configured, otherwise
    three simple controls (warmth, saturation, contrast)."""
    has_bake = True

    def bake(self, img):
        if self.cfg.get("lut"):
            return apply_cube_lut(img, Path(self.cfg["lut"]))
        out = img.copy()
        w = self.cfg.get("warmth", 0.0)
        out[..., 0] *= 1 + w          # R up
        out[..., 2] *= 1 - w * 0.8    # B down
        grey = out.mean(axis=2, keepdims=True)
        out = grey + (out - grey) * self.cfg.get("saturation", 1.0)
        out = (out - 0.5) * self.cfg.get("contrast", 1.0) + 0.5
        return np.clip(out, 0, 1)


@effect("bloom")
class Bloom(Effect):
    """Soft glow around highlights (halo, lamps, sky), screen-blended."""
    has_bake = True

    def bake(self, img):
        bright = np.clip((img - 0.6) / 0.4, 0, 1) * img
        r = int(self.cfg.get("radius", 18)) | 1
        glow = cv2.GaussianBlur(bright, (0, 0), sigmaX=r)
        s = self.cfg.get("strength", 0.2)
        return 1 - (1 - img) * (1 - glow * s)


def apply_cube_lut(img: np.ndarray, path: Path) -> np.ndarray:
    size, table = None, []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
        elif line and (line[0].isdigit() or line[0] in "-."):
            table.append([float(x) for x in line.split()[:3]])
    if size is None:
        raise ValueError(f"{path} is not a 3D .cube LUT")
    lut = np.asarray(table, np.float32).reshape(size, size, size, 3)  # [b][g][r] order in .cube files
    idx = np.clip(img, 0, 1) * (size - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, size - 1)
    f = idx - lo
    out = np.zeros_like(img)
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                w = ((f[..., 2] if db else 1 - f[..., 2]) * (f[..., 1] if dg else 1 - f[..., 1])
                     * (f[..., 0] if dr else 1 - f[..., 0]))[..., None]
                b = hi[..., 2] if db else lo[..., 2]
                g = hi[..., 1] if dg else lo[..., 1]
                r = hi[..., 0] if dr else lo[..., 0]
                out += w * lut[b, g, r]
    return out
