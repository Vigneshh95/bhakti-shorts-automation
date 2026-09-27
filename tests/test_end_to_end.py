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


def _add_override(episode, text):
    p = episode / "episode.toml"
    p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")


def _video_codec(path):
    out = subprocess.run([str(ROOT / "tools/ffmpeg/bin/ffprobe.exe"), "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_name,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


def test_x264_fallback_encoder_produces_a_valid_short(episode, monkeypatch, fake_voice):
    # the path taken on a machine without Intel Quick Sync
    _add_override(episode, '[video]\nencoder = "x264"\n')
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    res = pipeline.make_short(episode, out_date="2026-01-02")
    assert res.encoder.startswith("libx264")
    s = _video_codec(res.output)
    assert (s["codec_name"], s["width"], s["height"]) == ("h264", 1080, 1920)


def test_custom_overlay_video_is_screen_blended(episode, tmp_path, monkeypatch, fake_voice):
    overlay = tmp_path / "sparkles.mp4"
    subprocess.run([str(ROOT / "tools/ffmpeg/bin/ffmpeg.exe"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=540x960:d=1:r=30,drawbox=x=200:y=400:w=40:h=40:color=white:t=fill",
                    str(overlay)], check=True)
    _add_override(episode, '[effects.particles]\noverlay = "%s"\n' % overlay.as_posix())
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    res = pipeline.make_short(episode, out_date="2026-01-03")
    cap = cv2.VideoCapture(str(res.output))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 12)
    ok, frame = cap.read()
    assert ok
    # the overlay's white square (scaled 2x to 80x80 at 400,800) brightens that spot via screen blend
    assert frame[830:870, 430:470].mean() > 200


def test_missing_overlay_file_is_a_clear_error(episode, monkeypatch, fake_voice):
    _add_override(episode, '[effects.particles]\noverlay = "no/such/file.mp4"\n')
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    with pytest.raises(FileNotFoundError, match="overlay not found"):
        pipeline.make_short(episode, out_date="2026-01-04")


def _talking_clip(path, seconds=3, size="1210x2150"):
    # a stand-in "talking" video: FFmpeg's animated test pattern, which changes every frame
    subprocess.run([str(ROOT / "tools/ffmpeg/bin/ffmpeg.exe"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=s={size}:d={seconds}:r=25", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_talking_video_frames_replace_the_still_picture(tmp_path):
    from shorts.stages import talking, visuals
    clip = _talking_clip(tmp_path / "talk.mp4")
    src = talking.FrameSource(clip, (1210, 2150))
    a, b = src.at(0.0), src.at(2.0)
    assert a.shape == (2150, 1210, 3) and np.abs(a.astype(int) - b.astype(int)).mean() > 1
    still = np.zeros((2150, 1210, 3), np.uint8)
    segs = visuals.plan_segments([still], [(0, 3)], 3.0, {"zoom": 0.0, "pan": 0.0}, seed=1)
    segs[0].video = talking.FrameSource(clip, (1210, 2150))
    frames = [f for _, f in visuals.frames(segs, 1080, 1920, 5, 3.0, {"enabled": False})]
    assert frames[0].max() > 0  # the talking video's frames are used, not the black still picture
    assert np.abs(frames[0].astype(int) - frames[-1].astype(int)).mean() > 1  # and they change over time


def test_talking_head_enabled_end_to_end_and_falls_back_if_it_fails(episode, tmp_path, monkeypatch, fake_voice):
    from shorts.stages import talking
    (episode / "images" / "b.png").unlink()  # the talking head works on one picture
    p = episode / "episode.toml"
    p.write_text(p.read_text(encoding="utf-8") + "[talking]\nenabled = true\n", encoding="utf-8")
    monkeypatch.setattr(pipeline.tts, "FastPitchVoice", lambda *a, **k: fake_voice)
    seen = {}

    def fake_animate(picture, voice_wav, cfg, cache, work):
        seen["voice"] = voice_wav
        h, w = picture.shape[:2]
        return _talking_clip(tmp_path / "t.mp4", seconds=4, size=f"{w}x{h}")

    monkeypatch.setattr(talking, "animate", fake_animate)
    res = pipeline.make_short(episode, out_date="2026-01-05")
    assert "talking head" in res.stage_times and res.output.exists()
    assert seen["voice"].name == "voice_16k.wav" and seen["voice"].exists()  # voice-only track drives the lips

    monkeypatch.setattr(talking, "animate", lambda *a, **k: None)  # SadTalker failed: still picture instead
    assert pipeline.make_short(episode, out_date="2026-01-06").output.exists()
