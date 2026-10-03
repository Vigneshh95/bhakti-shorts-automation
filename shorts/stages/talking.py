"""Talking-head stage (optional, [talking] in config.toml): SadTalker animates the face in the
picture -- lips in sync with the processed voice, blinks, gentle head motion -- and pastes it
back into the full picture at its own resolution. Our renderer then applies motion, captions
and effects on top of that video exactly as it does for a still picture.

SadTalker runs in its own Python environment (.sadtalker_env) on the CPU and is slow (about
2 hours for a 40-second Short on this laptop), so its result is cached: a re-render or a
retry of the same day never repeats it. If it fails (e.g. no face found in the picture), the
Short is made from the still picture instead of being lost."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from shorts.cache import Cache
from shorts.config import ROOT
from shorts.log import log

TALKING_VERSION = "2"
VENDOR_RENDERER = Path(__file__).resolve().parent.parent / "vendor" / "sadtalker_make_animation.py"


def install_speedups(sadtalker: Path) -> None:
    """Puts our faster copy of SadTalker's frame loop in place (the original is kept as
    make_animation.py.orig). With the speed settings off it behaves exactly like the original."""
    target = sadtalker / "src/facerender/modules/make_animation.py"
    wanted = VENDOR_RENDERER.read_bytes()
    if target.exists() and target.read_bytes() == wanted:
        return
    backup = target.with_name("make_animation.py.orig")
    if target.exists() and not backup.exists():
        shutil.copyfile(target, backup)
    shutil.copyfile(VENDOR_RENDERER, target)
    log.info("  installed SadTalker speed-ups (original kept as %s)", backup.name)


def _resolve(p: str) -> Path:
    return Path(p) if Path(p).is_absolute() else ROOT / p


def animate(picture: np.ndarray, voice_wav: Path, cfg: dict, cache: Cache, work: Path) -> Path | None:
    """picture: the baked RGB image the renderer would otherwise use. Returns the talking
    video (same size as the picture), or None if SadTalker isn't available or failed."""
    t = cfg["talking"]
    python, sadtalker = _resolve(t["python"]), _resolve(t["dir"])
    if not python.exists() and t.get("method") == "kaggle":
        # No separate SadTalker environment (e.g. the cloud runner): the face is only *found* here,
        # which this Python can do with facexlib; the animation itself runs on Kaggle.
        import sys

        python = Path(sys.executable)
    if not python.exists() or not (sadtalker / "inference.py").exists():
        log.warning("  talking head skipped: SadTalker not found at %s", sadtalker)
        return None

    src = work / "talking_source.png"
    cv2.imwrite(str(src), cv2.cvtColor(picture, cv2.COLOR_RGB2BGR))
    options = {k: t[k] for k in ("size", "still", "preprocess", "expression_scale", "enhancer", "batch_size", "pose_style",
                                 "frame_step", "skip_silence", "method") if k in t}
    key = cache.key("talking", TALKING_VERSION, src, voice_wav, options)
    out, hit = cache.lookup("talking", key, ".mp4")
    if hit:
        log.info("  talking head: reusing the cached animation")
        return out

    if t.get("method") == "kaggle":
        from shorts.stages import kaggle_talk

        from shorts.stages import mouth

        try:
            points = mouth.find_landmarks(src, python, sadtalker, cache)
            if points is None:
                raise kaggle_talk.KaggleUnavailable("no face found in the picture")
            return kaggle_talk.animate(src, voice_wav, points, cfg["paths"]["ffmpeg"], work, out,
                                       int(t.get("kaggle_timeout_min", 40)))
        except kaggle_talk.KaggleUnavailable as e:
            if t.get("kaggle_fallback", "sadtalker") != "sadtalker":
                log.warning("  Kaggle unavailable (%s); no laptop fallback configured", e)
                return None
            log.warning("  Kaggle unavailable (%s); animating on this laptop instead (slower)", e)

    result_dir = work / "sadtalker"
    shutil.rmtree(result_dir, ignore_errors=True)
    result_dir.mkdir(parents=True)
    cmd = [str(python), str(sadtalker / "inference.py"), "--driven_audio", str(voice_wav.resolve()),
           "--source_image", str(src.resolve()), "--result_dir", str(result_dir.resolve()), "--cpu",
           "--preprocess", t["preprocess"], "--size", str(t["size"]), "--expression_scale", str(t["expression_scale"]),
           "--batch_size", str(t["batch_size"]), "--pose_style", str(t["pose_style"])]
    if t["still"]:
        cmd.append("--still")
    if t["enhancer"]:
        cmd += ["--enhancer", t["enhancer"]]

    install_speedups(sadtalker)
    env = {**os.environ,
           "SADTALKER_STEP": str(t.get("frame_step", 1)),
           "OMP_NUM_THREADS": str(t.get("threads", cfg["run"]["threads"]))}
    if t.get("skip_silence"):
        silent_file = work / "silent_frames.txt"
        flags = silent_frames(voice_wav)
        silent_file.write_text(" ".join("1" if s else "0" for s in flags))
        env["SADTALKER_SILENT_FILE"] = str(silent_file)
        log.info("  %d of %d frames are silent pauses (face reused there)", sum(flags), len(flags))
    log.info("  animating the face with SadTalker (the slow step on a CPU)…")
    log_path = work / "sadtalker.log"
    t0 = time.perf_counter()
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen(cmd, cwd=sadtalker, stdout=lf, stderr=subprocess.STDOUT, env=env)
        last = 0.0
        while proc.poll() is None:
            time.sleep(15)
            if time.perf_counter() - last > 600:  # a progress line every 10 minutes
                last = time.perf_counter()
                log.info("  …SadTalker still working (%d min so far)", (last - t0) // 60)
    videos = sorted(result_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    if proc.returncode != 0 or not videos:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-6:])
        log.warning("  SadTalker failed (exit %s); using the still picture instead. Last lines:\n%s", proc.returncode, tail)
        return None
    shutil.copyfile(videos[-1], out)
    log.info("  talking head done in %.0f min", (time.perf_counter() - t0) / 60)
    return out


def silent_frames(voice_wav: Path, fps: int = 25, rel_db: float = -38.0, min_run: int = 4, pad: int = 2) -> list[bool]:
    """One flag per video frame: True where the voice is silent. Only pauses of at least
    `min_run` frames count (not the tiny gaps inside words), and `pad` frames next to speech stay
    'talking' so the mouth can open and close smoothly around each line."""
    import soundfile as sf

    wav, sr = sf.read(voice_wav, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    hop = int(sr / fps)
    n = len(wav) // hop
    if n == 0:
        return []
    rms = np.sqrt((wav[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    quiet = rms < rms.max() * 10 ** (rel_db / 20)
    flags = [False] * n
    i = 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= min_run:
                for k in range(i + (pad if i > 0 else 0), j - (pad if j < n else 0)):
                    flags[k] = True
            i = j
        else:
            i += 1
    return flags


class FrameSource:
    """Reads a talking video's frames in order, matched to the renderer's timeline and resized
    to the picture's size if SadTalker rounded it."""

    def __init__(self, path: Path, size: tuple[int, int]):
        self.cap = cv2.VideoCapture(str(path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.size = size  # (width, height)
        self.index, self.current = -1, None

    def at(self, t: float) -> np.ndarray | None:
        want = min(int(round(t * self.fps)), max(self.count - 1, 0))
        while self.index < want:
            ok, frame = self.cap.read()
            if not ok:
                break  # past the end: keep showing the last frame
            self.index += 1
            self.current = frame
        if self.current is None:
            return None
        rgb = cv2.cvtColor(self.current, cv2.COLOR_BGR2RGB)
        if (rgb.shape[1], rgb.shape[0]) != self.size:
            rgb = cv2.resize(rgb, self.size, interpolation=cv2.INTER_LINEAR)
        return rgb
