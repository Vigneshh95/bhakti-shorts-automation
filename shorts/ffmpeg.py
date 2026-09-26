"""Thin wrappers around the bundled FFmpeg: run, probe, and pick the best available encoder."""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

from shorts.log import log


class FFmpegError(RuntimeError):
    pass


def run(ffmpeg: Path, args: list[str], cwd: Path | None = None) -> str:
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg failed (exit {res.returncode}):\n{tail}")
    return res.stderr


def probe_duration(ffprobe: Path, path: Path) -> float:
    res = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(res.stdout)["format"]["duration"])


@lru_cache(maxsize=None)
def qsv_works(ffmpeg: Path) -> bool:
    """Encodes a tiny test clip with Intel Quick Sync. The encoder being compiled in isn't
    enough: it also needs a working Intel GPU driver, so actually try it once per run."""
    res = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
         "-vf", "format=nv12", "-c:v", "h264_qsv", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return res.returncode == 0


def encoder_args(ffmpeg: Path, choice: str, quality: int, threads: int) -> tuple[list[str], str]:
    """Returns (ffmpeg args, human-readable encoder name). Quick Sync moves encoding off the
    CPU onto the Iris Xe media engine; x264 is the portable, slightly-slower fallback."""
    if choice in ("auto", "qsv") and qsv_works(ffmpeg):
        return ["-c:v", "h264_qsv", "-preset", "slower", "-global_quality", str(quality), "-look_ahead_depth", "20",
                "-profile:v", "high", "-pix_fmt", "nv12"], "h264_qsv (Intel Quick Sync)"
    if choice == "qsv":
        log.warning("Intel Quick Sync isn't available on this machine; falling back to x264.")
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality), "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-threads", str(threads)], "libx264 (CPU)"
