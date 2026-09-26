"""Effects registry.

An effect is a class registered with @effect("name") and switched on/off (and tuned) in
config.toml under [effects.name]. It implements whichever hooks it needs; WHERE a hook
runs is what keeps effects cheap:

  bake(img)          once per source image, before any frames exist; result is cached.
                     Use for anything static: colour grade, glow, sharpening.
  prepare(ctx)       once per video, before rendering (build sprites, masks...).
  frame(rgb, t)      every frame, in place, on the uint8 RGB frame. Keep it to cheap,
                     local work (small sprites, a precomputed mask) -- it runs ~1000x.

Text (captions, hook, outro, watermark) lives in stages/captions.py and is drawn by
libass inside the ffmpeg pass. See README "Adding an effect" for a worked example."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

REGISTRY: dict[str, type["Effect"]] = {}


def effect(name: str):
    def register(cls):
        cls.name = name
        REGISTRY[name] = cls
        return cls
    return register


@dataclass
class RenderContext:
    width: int
    height: int
    fps: int
    duration: float
    seed: int


class Effect:
    name = "effect"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def bake(self, img: np.ndarray) -> np.ndarray:  # float32 RGB 0..1
        return img

    def prepare(self, ctx: RenderContext) -> None:
        pass

    def frame(self, rgb: np.ndarray, t: float) -> None:  # uint8 RGB, modify in place
        pass

    has_bake = False
    has_frame = False


def enabled_effects(effects_cfg: dict) -> list[Effect]:
    from shorts.effects import image, overlays  # noqa: F401  (registers the built-ins)

    return [REGISTRY[name](c) for name, c in effects_cfg.items() if name in REGISTRY and c.get("enabled", False)]
