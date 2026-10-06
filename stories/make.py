"""Makes a story episode's video from its reviewed script (script.json in the episode folder):

  pictures   one per scene, painted on the free Kaggle GPU (the cast's fixed looks are in every
             prompt, so the characters stay the same people)
  voices     the laptop's Tamil voice, shaped per character (child, grandmother, Murugan, narrator)
  video      the Shorts engine's own parts in 16:9: each picture is on screen exactly while its
             scene's lines are spoken, with slow camera movement, captions and music

Everything is cached: a re-run only redoes what changed."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from shorts.cache import Cache
from shorts.config import ROOT, deep_merge, load_config
from shorts.effects import enabled_effects
from shorts.log import log
from shorts.stages import audio, captions, kaggle_talk, render, tts, visuals
from shorts.stages.tts import LineAudio, Word
from stories import script as S

PICTURE_RUNNER = ROOT / "shorts" / "vendor" / "kaggle_pictures.py"
# Long videos are widescreen: every picture is painted 16:9 FOR the story (multiples of 16; the
# renderer scales it to 1920x1080). The tall 9:16 pictures of the Shorts folders are never used here.
PICTURE_SIZE = (1344, 768)

# What a story video changes in the Shorts engine's settings (config.toml stays as it is).
VIDEO = {
    "video": {"width": 1920, "height": 1080},
    "voice": {"style": "story", "line_gap_ms": 550, "lead_in_ms": 1200, "tail_ms": 2500,
              "styles": {"story": {"speaker": "female", "semitones": 0.0, "pace": 1.0, "formant": "preserved",
                                   "eq_gain_db": 0.0, "compress": True}}},
    "audio": {"bgm_db": -21.0, "duck_ratio": 3},
    "captions": {"size": 58, "words_per_caption": 6, "position_y": 0.87, "outline": 4},
    # The pictures are painted wide for the story, so nearly all of each is shown: a small margin
    # (3%) and a gentle 4% zoom, where Shorts crop 12% and zoom 8%.
    "effects": {"kenburns": {"zoom": 0.04, "pan": 0.02, "loop": False, "headroom": 1.03},
                "particles": {"count": 30, "opacity": 0.5},
                "glow_pulse": {"enabled": False},
                "watermark": {"lines": ["BrahmaNadagam"], "position_y": 0.06, "opacity": 0.45},
                "hook": {"duration_s": 2.6, "position_y": 0.14},
                "outro": {"duration_s": 2.4, "position_y": 0.14},
                "fade": {"enabled": True}},
    "talking": {"enabled": False},
}


def paint(script: dict, folder: Path, work: Path, timeout_min: int = 240) -> list[Path]:
    """One picture per scene in <folder>/pictures (scene_01.png ...); only missing ones are painted."""
    pictures = folder / "pictures"
    pictures.mkdir(parents=True, exist_ok=True)
    paths = [pictures / f"scene_{i:02d}.png" for i in range(1, len(script["scenes"]) + 1)]
    jobs = [{"name": p.stem, "prompt": S.picture_prompt(sc, script.get("person_look", "")), "seed": 4000 + i}
            for i, (p, sc) in enumerate(zip(paths, script["scenes"])) if not p.exists()]
    if not jobs:
        return paths
    runner = PICTURE_RUNNER.read_text(encoding="utf-8")
    size = "WIDTH, HEIGHT = 816, 1456"
    if "JOBS = []" not in runner or size not in runner:
        raise RuntimeError("the picture runner template has changed (JOBS / WIDTH, HEIGHT markers)")
    code = runner.replace("JOBS = []", "JOBS = " + json.dumps(jobs), 1).replace(
        size, f"WIDTH, HEIGHT = {PICTURE_SIZE[0]}, {PICTURE_SIZE[1]}", 1)
    log.info("  painting %d scene(s) on your Kaggle GPU (about %d min)…", len(jobs), 14 + 4 * len(jobs))
    dest = kaggle_talk.run_kernel("story-pictures", code, work, timeout_min, doing="painting")
    archive = dest / "pictures.zip"
    if not archive.exists():
        raise RuntimeError(f"The Kaggle picture run finished without pictures: {kaggle_talk._tail(dest)}")
    with zipfile.ZipFile(archive) as z:
        z.extractall(pictures)
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise RuntimeError(f"pictures not painted: {', '.join(missing)} ({kaggle_talk._tail(dest)})")
    return paths


def _shape(line: LineAudio, style: dict, ffmpeg: Path, cache: Cache) -> LineAudio:
    """The spoken line in its character's voice: pitch and pace changed, word timings kept in step."""
    pitch, pace = 2 ** (style["semitones"] / 12), style["pace"]
    if abs(pitch - 1) < 1e-3 and abs(pace - 1) < 1e-3:
        return line
    out, hit = cache.lookup("story_voice", cache.key("story_voice", line.wav_path, style), ".wav")
    if not hit:
        tmp = out.with_suffix(".tmp.wav")
        subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-i", str(line.wav_path), "-af",
                        f"rubberband=pitch={pitch:.5f}:tempo={pace:.5f}:formant=preserved:pitchq=quality",
                        str(tmp)], check=True)
        tmp.replace(out)
    duration = sf.info(out).duration
    words = [Word(w.text, w.start / pace, w.end / pace) for w in line.words]
    return LineAudio(line.text, out, line.sample_rate, duration, words)


def make(folder: Path, settings: dict) -> Path:
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    cfg = deep_merge(load_config(), VIDEO)
    cfg["paths"] = {**cfg["paths"]}
    cfg["effects"]["hook"]["text"] = script["title_ta"]
    cfg["effects"]["outro"]["text"] = script["source_line_ta"]
    cache = Cache(cfg["paths"]["cache"])
    work = cfg["paths"]["cache"] / "work" / f"story_{folder.name}"
    work.mkdir(parents=True, exist_ok=True)
    ff = cfg["paths"]["ffmpeg"]

    pictures = paint(script, folder, work)
    for p in pictures:   # a tall or square picture would be cropped to a strip: refuse it
        with Image.open(p) as im:
            if im.width < im.height * 1.6:
                raise RuntimeError(f"{p.name} is {im.width}x{im.height}: story pictures must be wide (16:9)")

    # voices: every line by its speaker's voice; remember which scene each line belongs to
    voice = tts.FastPitchVoice(cfg["paths"]["checkpoints"], int(cfg["run"]["threads"]))
    spoken, scene_of = [], []
    for i, scene in enumerate(script["scenes"]):
        for line in scene["lines"]:
            style = settings["voices"][S.CAST[line["speaker"]]["voice"]]
            raw = tts.synthesize_lines([line["text"]], style["speaker"], voice, cache)[0]
            spoken.append(_shape(raw, style, ff, cache))
            scene_of.append(i)
    del voice
    aud = audio.make_audio(spoken, cfg, work)
    log.info("  %.0f s of story, %d lines, %d scenes", aud.duration, len(spoken), len(pictures))

    ass = captions.write_ass(work / "captions.ass", aud.words, aud.duration, cfg, script["title_ta"])

    # each picture is on screen from just before its first line to just before the next scene's
    effects = enabled_effects(cfg["effects"])
    images = [visuals.bake_image(p, cfg, effects, cache) for p in pictures]
    starts = []
    for i in range(len(images)):
        first = scene_of.index(i)
        starts.append(0.0 if i == 0 else (aud.line_spans[first - 1][1] + aud.line_spans[first][0]) / 2)
    bounds = [*starts, aud.duration]
    kb, rng = cfg["effects"]["kenburns"], np.random.default_rng(7)
    segments = []
    for i, image in enumerate(images):
        zoom_in = i % 2 == 0
        z0, z1 = (1.0, 1.0 + kb["zoom"]) if zoom_in else (1.0 + kb["zoom"], 1.0)
        direction = rng.uniform(-1, 1, 2) * (kb["pan"] / max(kb.get("headroom", visuals.HEADROOM) - 1, 1e-6))
        segments.append(visuals.Segment(image, bounds[i], bounds[i + 1], z0, z1, (float(direction[0]), float(direction[1]))))

    out = settings["paths"]["output"] / f"{folder.name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    render.render(segments, effects, ass, aud, cfg, work, out)
    shutil.copyfile(out, folder / "video.mp4")
    log.info("✅ %s (%.0f s)", out, aud.duration)
    return out
