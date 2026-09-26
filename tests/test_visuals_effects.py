import cv2
import numpy as np

from shorts.cache import Cache
from shorts.effects import REGISTRY, RenderContext, enabled_effects
from shorts.stages import visuals


def _image(tmp_path, w=800, h=600):
    p = tmp_path / "src.png"
    img = np.zeros((h, w, 3), np.uint8)
    cv2.rectangle(img, (100, 100), (700, 500), (40, 160, 220), -1)
    cv2.imwrite(str(p), img)
    return p


def test_bake_cover_fits_with_headroom_and_caches(tmp_path, cfg):
    cache = Cache(tmp_path / "cache")
    effects = enabled_effects(cfg["effects"])
    img = visuals.bake_image(_image(tmp_path), cfg, effects, cache)
    assert img.shape == (round(1920 * visuals.HEADROOM), round(1080 * visuals.HEADROOM), 3)
    visuals.bake_image(_image(tmp_path), cfg, effects, cache)
    assert cache.hits == 1  # second bake of the same image + settings is a cache hit


def test_cuts_between_images_land_between_lines():
    imgs = [np.zeros((10, 10, 3), np.uint8)] * 2
    spans = [(0.0, 2.0), (3.0, 5.0), (6.0, 8.0), (9.0, 11.0)]
    segs = visuals.plan_segments(imgs, spans, 12.0, {"zoom": 0.08, "pan": 0.03}, seed=1)
    assert [round(s.end, 2) for s in segs] == [5.5, 12.0]  # the cut sits in the pause after line 2


def test_frames_are_full_size_and_actually_move():
    img = (np.random.default_rng(0).random((2150, 1210, 3)) * 255).astype(np.uint8)
    segs = visuals.plan_segments([img], [(0, 2)], 2.0, {"zoom": 0.08, "pan": 0.0}, seed=1)
    frames = list(visuals.frames(segs, 1080, 1920, 5, 2.0, {"enabled": False}))
    assert len(frames) == 10
    assert frames[0][1].shape == (1920, 1080, 3)
    assert np.abs(frames[0][1].astype(int) - frames[-1][1].astype(int)).mean() > 1  # Ken Burns moved the image


def test_crossfade_only_blends_near_the_cut():
    a = np.full((2150, 1210, 3), 0, np.uint8)
    b = np.full((2150, 1210, 3), 200, np.uint8)
    segs = visuals.plan_segments([a, b], [(0, 1), (2, 3)], 4.0, {"zoom": 0.0, "pan": 0.0}, seed=1)
    fr = {round(t, 2): f.mean() for t, f in visuals.frames(segs, 1080, 1920, 10, 4.0, {"duration_s": 0.8})}
    assert fr[0.5] == 0 and fr[3.5] == 200
    assert 0 < fr[1.5] < 200  # mid-transition


def test_frame_effects_touch_the_frame(cfg):
    ctx = RenderContext(1080, 1920, 25, 5.0, seed=3)
    for name in ("particles", "vignette"):
        eff = REGISTRY[name](cfg["effects"][name])
        eff.prepare(ctx)
        rgb = np.full((1920, 1080, 3), 120, np.uint8)
        eff.frame(rgb, 1.0)
        assert not np.all(rgb == 120), name


def test_bake_effects_warm_the_image(cfg):
    img = np.full((50, 50, 3), 0.5, np.float32)
    out = REGISTRY["grade"](cfg["effects"]["grade"]).bake(img)
    assert out[..., 0].mean() > out[..., 2].mean()  # warmer: red above blue


def test_disabled_effects_are_not_loaded(cfg):
    cfg["effects"]["bloom"]["enabled"] = False
    assert "bloom" not in [e.name for e in enabled_effects(cfg["effects"])]
