"""End-to-end: episode folder in, finished MP4 out, through every real stage and the real
bundled FFmpeg (captions, effects, loudness, encoder, mux). Only the voice model is
swapped for a stand-in so the test runs in seconds instead of loading 1.6 GB of weights."""
import json
import subprocess

import cv2
import numpy as np
import pytest

from shorts import pipeline
from shorts.config import ROOT


@pytest.fixture
def episode(tmp_path):
    ep = tmp_path / "ep"
    (ep / "images").mkdir(parents=True)
    img = np.zeros((1600, 900, 3), np.uint8)
    cv2.circle(img, (450, 800), 300, (30, 180, 240), -1)
    cv2.imwrite(str(ep / "images" / "a.png"), img)
    cv2.imwrite(str(ep / "images" / "b.png"), 255 - img)
    (ep / "lines.txt").write_text("முருகன் சொல்வது.\nதாயின் ஆசியே உனது முதல் வெற்றி.\n", encoding="utf-8")
    (ep / "episode.toml").write_text(
        '[episode]\ntitle = "சோதனை"\n[run]\npreset = "fast"\n[paths]\ncache = "%s"\noutput = "%s"\n'
        % ((tmp_path / "cache").as_posix(), (tmp_path / "out").as_posix()), encoding="utf-8")
    return ep


def test_make_short_end_to_end(episode, tmp_path, monkeypatch, fake_voice):
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    res = pipeline.make_short(episode, out_date="2026-01-01")

    assert res.output == tmp_path / "out" / "muruganShorts_2026-01-01.mp4"
    assert res.output.with_suffix(".txt").read_text(encoding="utf-8").strip() == "சோதனை"  # for the uploader
    probe = json.loads(subprocess.run(
        [str(ROOT / "tools/ffmpeg/bin/ffprobe.exe"), "-v", "error", "-show_entries",
         "stream=codec_type,width,height:format=duration", "-of", "json", str(res.output)],
        capture_output=True, text=True, check=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in probe["streams"])
    assert abs(float(probe["format"]["duration"]) - res.duration) < 0.2
    assert set(res.stage_times) == {"script", "tts", "audio", "captions", "visuals", "render"}

    # second run: every line and image comes from the cache, the voice is never called again
    calls = fake_voice.calls
    pipeline.make_short(episode, out_date="2026-01-01")
    assert fake_voice.calls == calls


def test_missing_images_is_a_clear_error(episode, monkeypatch, fake_voice):
    for p in (episode / "images").iterdir():
        p.unlink()
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    with pytest.raises(FileNotFoundError, match="No images"):
        pipeline.make_short(episode)
