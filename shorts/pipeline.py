"""Runs the stages in order: script -> TTS -> audio -> captions -> visuals -> render."""
from __future__ import annotations

import os

import ctypes
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import psutil

from shorts import ffmpeg
from shorts.cache import Cache
from shorts.config import load_config
from shorts.effects import enabled_effects
from shorts.log import StageTimer, log
from shorts.stages import audio as audio_stage
from shorts.stages import captions, mouth, render, script, talking, tts, visuals


@dataclass
class RunResult:
    output: Path
    duration: float
    stage_times: dict[str, float]
    peak_rss_mb: float
    encoder: str
    size_mb: float
    cache_hits: int = 0
    cache_misses: int = 0
    extra: dict = field(default_factory=dict)


class KeepAwake:
    """Asks Windows not to idle-sleep while a Short is being made. Without it, an
    unattended run stalls for as long as the laptop sits in Modern Standby (seen in
    testing: a 30 s render took 20 min, matching a standby window in the event log).
    This is a per-process request, not a settings change: it ends when the run ends,
    and closing the lid or pressing the power button still sleeps the laptop."""

    _ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001

    def __init__(self, enabled: bool):
        self.enabled = enabled and sys.platform == "win32"

    def __enter__(self):
        if self.enabled:
            ctypes.windll.kernel32.SetThreadExecutionState(self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED)
        return self

    def __exit__(self, *exc):
        if self.enabled:
            ctypes.windll.kernel32.SetThreadExecutionState(self._ES_CONTINUOUS)


class PeakMemory:
    """Samples RSS of this process + children (ffmpeg) so the summary reports real peak use."""

    def __init__(self):
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        me = psutil.Process()
        while not self._stop.is_set():
            try:
                rss = me.memory_info().rss + sum(c.memory_info().rss for c in me.children(recursive=True))
                self.peak = max(self.peak, rss)
            except psutil.Error:
                pass
            time.sleep(0.2)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def _light_lipsync(picture, voice_wav, cfg: dict, cache: Cache, work: Path):
    """Our own mouth animation (seconds, not hours); None = keep the still picture."""
    import cv2

    t = cfg["talking"]
    src = work / "talking_source.png"
    cv2.imwrite(str(src), cv2.cvtColor(picture, cv2.COLOR_RGB2BGR))
    python, sadtalker = talking._resolve(t["python"]), talking._resolve(t["dir"])
    points = mouth.find_landmarks(src, python, sadtalker, cache) if python.exists() else None
    if points is None:
        log.warning("  no face found for lip-sync; using the still picture")
        return None
    log.info("  light lip-sync: mouth follows the voice")
    return mouth.MouthAnimator(picture, points, voice_wav, cfg["video"]["fps"], t, seed=cfg["effects"]["kenburns"].get("seed", 7))


def work_folder(cfg: dict, episode_dir: Path) -> Path:
    """Scratch files (voice, mix, captions) for ONE episode. Named after the episode's whole path
    under episodes/, not just its last part: the two daily series both have a folder called
    <date>, and when they shared one scratch folder a run rendered with the other's audio and
    captions (Murugan's picture with Mahaperiyava's voice, 2026-10-04)."""
    try:
        tag = "_".join(episode_dir.resolve().relative_to(cfg["paths"]["episodes"].resolve()).parts)
    except ValueError:
        tag = "_".join(episode_dir.resolve().parts[-2:])
    return cfg["paths"]["cache"] / "work" / tag


def make_short(episode_dir: Path, preset: str | None = None, out_date: str | None = None,
               voice_style: str | None = None, output: Path | None = None) -> RunResult:
    cfg = load_config(episode_dir, preset)
    if voice_style:
        cfg["voice"]["style"] = voice_style
    if cfg["run"]["low_priority"]:
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)  # children (ffmpeg) inherit it
        except (AttributeError, psutil.Error):
            pass
    for key in ("ffmpeg", "ffprobe"):
        if not cfg["paths"][key] or not cfg["paths"][key].exists():
            raise FileNotFoundError(f"FFmpeg not found at {cfg['paths'][key]} -- see README 'Setup'.")

    timer, cache = StageTimer(), Cache(cfg["paths"]["cache"])
    work = work_folder(cfg, episode_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_dir = cfg["paths"]["output"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = output or out_dir / cfg["video"]["filename"].format(date=out_date or date.today().isoformat())
    if out_path.exists():
        log.warning("%s already exists and will be replaced (use --date or --output to keep both)", out_path.name)

    with KeepAwake(cfg["run"].get("keep_awake", True)), PeakMemory() as mem:
        with timer.stage("script"):
            ep = script.load_episode(episode_dir)
            log.info("  %d lines, %d image(s), voice '%s', preset '%s'",
                     len(ep.lines), len(ep.images), cfg["voice"]["style"], cfg["run"]["preset"])

        with timer.stage("tts"):
            style = cfg["voice"]["styles"][cfg["voice"]["style"]]
            if cfg["voice"].get("engine", "fastpitch") == "indicf5":  # a cloned voice, spoken on Kaggle
                from shorts.stages import tts_indicf5

                lines = tts_indicf5.synthesize_lines(ep.lines, cfg, cache, work)
            else:
                voice = tts.FastPitchVoice(cfg["paths"]["checkpoints"], int(cfg["run"]["threads"]))
                lines = tts.synthesize_lines(ep.lines, style["speaker"], voice, cache)
                del voice  # release ~1.2 GB of model weights before rendering

        if cfg["voice"].get("convert_to"):
            with timer.stage("voice conversion"):  # the same words, in the reference voice's timbre
                from shorts.stages import voice_convert

                lines = voice_convert.convert(lines, cfg, cache, work)

        with timer.stage("audio"):
            aud = audio_stage.make_audio(lines, cfg, work)
            log.info("  %.1f s of audio, %d timed words", aud.duration, len(aud.words))

        with timer.stage("captions"):
            hook = cfg["effects"]["hook"]["text"] or ep.title or ep.lines[0]
            ass = captions.write_ass(work / "captions.ass", aud.words, aud.duration, cfg, hook)

        with timer.stage("visuals"):
            effects = enabled_effects(cfg["effects"])
            images = [visuals.bake_image(p, cfg, effects, cache) for p in ep.images]
            segments = visuals.plan_segments(images, aud.line_spans, aud.duration, cfg["effects"]["kenburns"],
                                             cfg["effects"]["kenburns"].get("seed", 7))

        if cfg.get("talking", {}).get("enabled"):
            with timer.stage("talking head"):
                if len(images) != 1:
                    log.warning("  talking head needs exactly one picture (this episode has %d); skipped", len(images))
                elif cfg["talking"].get("method", "sadtalker") == "light":
                    segments[0].video = _light_lipsync(images[0], aud.voice_path, cfg, cache, work)
                else:
                    video = talking.animate(images[0], aud.voice_path, cfg, cache, work)
                    if video:
                        h, w = images[0].shape[:2]
                        segments[0].video = talking.FrameSource(video, (w, h))

        if (cfg.get("talking", {}).get("enabled") and os.environ.get("SHORTS_REQUIRE_TALKING") == "1"
                and len(images) == 1 and segments[0].video is None):
            # Unattended runs: a Short whose face should talk isn't quietly made with a still picture.
            raise RuntimeError("The talking face couldn't be made (see the lines above); nothing was rendered. "
                               "A later run will try again.")

        with timer.stage("render"):
            enc_name = render.render(segments, effects, ass, aud, cfg, work, out_path)

    # The uploader takes its title "highlight" from a same-named .txt next to the video.
    out_path.with_suffix(".txt").write_text((ep.title or ep.lines[0]) + "\n", encoding="utf-8")

    result = RunResult(out_path, aud.duration, timer.times, mem.peak / 2**20, enc_name,
                       out_path.stat().st_size / 2**20, cache.hits, cache.misses)
    log.info("%s", timer.summary())
    log.info("Peak memory %.0f MB · cache %d hit / %d miss · %s", result.peak_rss_mb, cache.hits, cache.misses, enc_name)
    log.info("✅ %s  (%.1f s video, %.1f MB)", out_path, aud.duration, result.size_mb)
    return result
