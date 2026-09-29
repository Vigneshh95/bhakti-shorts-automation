"""Light lip-sync ([talking] method = "light"): our own mouth animation, no heavy AI model and no
licence restrictions. It finds the face's 68 landmarks once per picture (SadTalker's face
detector + alignment model, CPU, ~20 s, cached), then for every frame:

- opens the jaw / lower lip in proportion to how loud the voice is at that moment (fast attack,
  softer release, closed during pauses), with a smooth fall-off so the chin and cheeks follow;
- paints a soft dark inner mouth in the opening;
- blinks every few seconds (seeded, so re-renders are identical).

Everything is precomputed; each frame only remaps a small box around the mouth/eyes, so the
whole Short's lip-sync costs seconds instead of the ~1-2 hours SadTalker takes on this CPU."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from shorts.cache import Cache
from shorts.log import log

MOUTH_VERSION = "1"
LANDMARKS_SCRIPT = Path(__file__).resolve().parent.parent / "vendor" / "face_landmarks.py"


def find_landmarks(picture_png: Path, python: Path, sadtalker: Path, cache: Cache) -> np.ndarray | None:
    """68 (x, y) face landmarks in the picture's own pixels, or None if no face was found."""
    key = cache.key("landmarks", MOUTH_VERSION, picture_png)
    path, hit = cache.lookup("landmarks", key, ".json")
    if not hit:
        res = subprocess.run([str(python), str(LANDMARKS_SCRIPT), str(picture_png.resolve())], cwd=sadtalker,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        line = next((l for l in reversed(res.stdout.splitlines()) if l.startswith("{")), "")
        if res.returncode != 0 or not line:
            log.warning("  face landmarks failed: %s", (res.stderr or res.stdout).strip().splitlines()[-1:] or "?")
            return None
        path.write_text(line, encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    return np.asarray(data["points"], np.float32) if data.get("found") else None


def mouth_openness(voice_wav: Path, fps: int, n_frames: int) -> np.ndarray:
    """0..1 per video frame from the voice's loudness: fast to open, slower to close, and a
    small texture from the syllables so it doesn't look like a hinge."""
    import soundfile as sf

    wav, sr = sf.read(voice_wav, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    hop = sr / fps
    chunks = [wav[int(i * hop): int((i + 1) * hop)] for i in range(n_frames)]
    rms = np.array([np.sqrt(np.mean(c ** 2) + 1e-12) if len(c) else 0.0 for c in chunks])  # past the end: silent
    db = 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-9)
    target = np.clip((db + 32) / 26, 0, 1) ** 0.9  # -32 dB below peak = closed, -6 dB = fully open
    out = np.zeros(n_frames, np.float32)
    level = 0.0
    for i, v in enumerate(target):
        level += (v - level) * (0.65 if v > level else 0.4)  # attack / release per frame
        out[i] = level
    return out


class MouthAnimator:
    """Frame source (same interface as talking.FrameSource): at(t) returns the picture with the
    mouth (and eyes) animated for time t."""

    def __init__(self, picture: np.ndarray, points: np.ndarray, voice_wav: Path, fps: int, cfg: dict, seed: int = 7):
        self.base = picture
        self.fps = fps
        H, W = picture.shape[:2]
        p = points
        n_frames = int(np.ceil(sf_duration(voice_wav) * fps)) + 1
        self.open = np.minimum(mouth_openness(voice_wav, fps, n_frames), 0.85) * float(cfg.get("mouth_strength", 1.0))

        # --- mouth geometry (68-point scheme: 48-59 outer lips, 60-67 inner lips, 8 chin, 33 nose)
        left, right = p[48], p[54]
        self.width = float(np.linalg.norm(right - left))
        inner = p[60:68]
        self.center = inner.mean(axis=0)
        self.drop = 0.30 * self.width   # how far the lower lip/jaw moves at full opening (a child's speech: small)
        self.lift = 0.06 * self.width   # the upper lip moves up a little too
        chin_y, nose_y = float(p[8][1]), float(p[33][1])
        cx, cy = self.center
        x0, x1 = int(max(0, cx - 1.3 * self.width)), int(min(W, cx + 1.3 * self.width))
        y0, y1 = int(max(0, nose_y)), int(min(H, chin_y + 0.5 * self.width))
        self.box = (x0, y0, x1, y1)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        gx = np.exp(-(((xx - cx) / (0.62 * self.width)) ** 2))  # strongest at the mouth centre
        below = np.where(yy >= cy,
                         np.where(yy <= chin_y, 1 - 0.45 * (yy - cy) / max(chin_y - cy, 1),
                                  0.55 * np.exp(-(((yy - chin_y) / (0.35 * self.width)) ** 2))), 0)
        above = np.where(yy < cy, np.clip((yy - nose_y) / max(cy - nose_y, 1), 0, 1), 0)
        self.map_x = xx
        self.map_y = yy
        self.down_field = (gx * below).astype(np.float32)   # x drop  -> sample from higher up
        self.up_field = (gx * above).astype(np.float32)     # x lift  -> sample from lower down
        # inner mouth polygon: corners fixed, upper inner lip up, lower inner lip down
        self.inner = inner.copy()
        for corner in (0, 4):  # keep the dark inside away from the lip corners
            self.inner[corner] = inner[corner] + (self.center - inner[corner]) * 0.22
        self.inner_w = np.exp(-(((inner[:, 0] - cx) / (0.5 * self.width)) ** 2))
        self.inner_is_lower = np.array([False, False, False, False, False, True, True, True])  # 60-67
        self.inner_is_lower[4] = False  # 64 is the right corner

        # --- eyes (36-41 right, 42-47 left) for blinks
        self.eyes = [p[36:42], p[42:48]]
        # Skin tone for the eyelids, from plain skin: the nose bridge (27-29) and the cheek just
        # under each eye. (Just above the eye is lashes/shadow in illustrations: too dark.)
        patches = []
        r = max(3, int(0.05 * self.width))
        spots = [p[28], p[29]] + [e.mean(axis=0) + [0, 1.6 * (e[:, 1].max() - e[:, 1].min() + 4)] for e in self.eyes]
        for sx, sy in spots:
            patch = picture[int(max(0, sy - r)):int(min(H, sy + r)), int(max(0, sx - r)):int(min(W, sx + r))]
            if patch.size:
                patches.append(patch.reshape(-1, 3))
        self.skin = (np.median(np.concatenate(patches), axis=0).astype(np.float32) if patches
                     else np.array([225, 175, 145], np.float32))
        rng = np.random.default_rng(seed)
        self.blinks = []
        t = rng.uniform(1.5, 3.0)
        while t < n_frames / fps:
            self.blinks.append(t)
            t += rng.uniform(2.8, 5.5)
        self.blink_on = bool(cfg.get("blink", False))  # off by default: a drawn lid on painted eyes looked unnatural

    def _blink_amount(self, t: float) -> float:
        for b in self.blinks:
            d = t - b
            if 0 <= d <= 0.22:
                return float(np.sin(np.pi * d / 0.22))  # close then open over ~5 frames
        return 0.0

    def at(self, t: float) -> np.ndarray:
        i = min(int(round(t * self.fps)), len(self.open) - 1)
        o = float(self.open[i])
        blink = self._blink_amount(t) if self.blink_on else 0.0
        if o < 0.02 and blink < 0.02:
            return self.base
        img = self.base.copy()
        if o >= 0.02:
            self._open_mouth(img, o)
        if blink >= 0.02:
            for eye in self.eyes:
                self._close_eye(img, eye, blink)
        return img

    def _open_mouth(self, img: np.ndarray, o: float) -> None:
        x0, y0, x1, y1 = self.box
        src_y = self.map_y - self.down_field * (self.drop * o) + self.up_field * (self.lift * o)
        region = cv2.remap(self.base, self.map_x, src_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        # inner mouth: the gap between the moved lips, soft-edged dark red
        pts = self.inner.copy()
        pts[self.inner_is_lower, 1] += self.drop * o * self.inner_w[self.inner_is_lower]
        upper = ~self.inner_is_lower
        upper[[0, 4]] = False  # corners stay put
        pts[upper, 1] -= self.lift * o * self.inner_w[upper]
        mask = np.zeros((y1 - y0, x1 - x0), np.float32)
        cv2.fillPoly(mask, [np.round(pts - [x0, y0]).astype(np.int32)], 1.0, lineType=cv2.LINE_AA)
        k = max(3, int(self.width * 0.08)) | 1
        mask = cv2.GaussianBlur(mask, (k, k), 0)[..., None]
        yy = np.arange(y1 - y0, dtype=np.float32)[:, None, None]
        top = pts[:, 1].min() - y0
        shade = np.clip((yy - top) / max(self.drop * o, 1), 0, 1)  # darker at the top, a hint of tongue below
        inside = (1 - shade) * np.array([45, 18, 22], np.float32) + shade * np.array([120, 45, 50], np.float32)
        out = region.astype(np.float32) * (1 - mask * 0.92) + inside * (mask * 0.92)
        img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)

    def _close_eye(self, img: np.ndarray, eye: np.ndarray, amount: float) -> None:
        """Draws the upper eyelid coming down over the eye: skin coloured from just above the
        eye, with a dark lash line at its edge. Eyebrows and the rest of the face stay put."""
        H, W = img.shape[:2]
        ex0, ey0 = eye.min(axis=0)
        ex1, ey1 = eye.max(axis=0)
        w, h = ex1 - ex0, max(ey1 - ey0, 2.0)
        x0, x1 = int(max(0, ex0 - 0.25 * w)), int(min(W, ex1 + 0.25 * w))
        y0, y1 = int(max(0, ey0 - 0.9 * h)), int(min(H, ey1 + 0.6 * h))
        skin = self.skin
        poly = (eye - [x0, y0]).astype(np.float32)
        centre = poly.mean(axis=0)
        poly = centre + (poly - centre) * [1.15, 1.35]  # cover the lashes around the eye too
        eye_mask = np.zeros((y1 - y0, x1 - x0), np.float32)
        cv2.fillPoly(eye_mask, [np.round(poly).astype(np.int32)], 1.0, lineType=cv2.LINE_AA)
        top, bottom = poly[:, 1].min(), poly[:, 1].max()
        edge = top + (bottom - top) * amount  # how far the lid has come down
        rows = np.arange(y1 - y0, dtype=np.float32)[:, None]
        lid = np.clip((edge - rows) / 1.5 + 0.5, 0, 1) * eye_mask  # soft lid edge
        k = max(3, int(h * 0.3)) | 1
        lid = cv2.GaussianBlur(lid, (k, k), 0)[..., None]
        region = img[y0:y1, x0:x1].astype(np.float32)
        lid_skin = skin * (0.92 + 0.08 * (rows[..., None] - top) / max(bottom - top, 1))  # slight shading
        out = region * (1 - lid) + lid_skin * lid
        # lash line along the lid's edge (only once the lid is well down)
        if amount > 0.35:
            lash = np.exp(-((rows - edge) / 1.3) ** 2) * eye_mask
            lash = (cv2.GaussianBlur(lash, (3, 3), 0) * min(1.0, (amount - 0.35) / 0.4))[..., None]
            out = out * (1 - lash * 0.85) + np.array([40, 25, 20], np.float32) * (lash * 0.85)
        img[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)


def sf_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    return info.frames / info.samplerate
