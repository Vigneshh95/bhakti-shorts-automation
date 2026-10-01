"""Voice conversion ([voice] convert_to = "voices/<name>.wav"): after the laptop's own Tamil
voice has spoken the lines, Seed-VC on your free Kaggle GPU re-voices them in the timbre of the
reference recording (shorts/vendor/kaggle_seedvc.py). No sign-in or training is needed.

The words and their timing are kept, so the word timings FastPitch already gave stay valid and
the captions remain in sync. All lines go to Kaggle joined in one file (one model load), and
come back cut at the same places; each converted line is cached (line audio + reference), so
a re-run never goes back to Kaggle."""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from shorts.cache import Cache, file_digest
from shorts.config import ROOT
from shorts.log import log
from shorts.stages import kaggle_talk
from shorts.stages.tts import LineAudio

VERSION = "1"
RUNNER = ROOT / "shorts" / "vendor" / "kaggle_seedvc.py"
KERNEL_SLUG = "periyava-revoice"
GAP_S = 0.7      # silence between lines in the joined file: keeps the model from blending them
MAX_REF_S = 25   # Seed-VC reads at most ~25 s of reference


def convert(lines: list[LineAudio], cfg: dict, cache: Cache, work: Path) -> list[LineAudio]:
    v = cfg["voice"]
    ref = Path(v["convert_to"])
    ref = ref if ref.is_absolute() else ROOT / ref
    if not ref.exists():
        raise FileNotFoundError(f"Voice reference missing: {ref}")
    options = {"steps": int(v.get("convert_steps", 30)), "cfg": float(v.get("convert_cfg", 0.7))}
    signature = [VERSION, file_digest(ref), options]
    outs = [cache.lookup("voice_vc", cache.key("voice_vc", l.wav_path, signature), ".wav") for l in lines]
    if not all(hit for _, hit in outs):
        log.info("  re-voicing %d line(s) in the reference voice on your Kaggle GPU (Seed-VC)…", len(lines))
        _convert_on_kaggle(lines, ref, options, cfg, work, [p for p, _ in outs])
    else:
        log.info("  converted voice: all %d lines cached", len(lines))
    return [LineAudio(l.text, p, l.sample_rate, l.duration, l.words) for l, (p, _) in zip(lines, outs)]


def _ogg(ffmpeg: Path, src: Path, dst: Path, bitrate: str, extra: list[str] = ()) -> bytes:
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-i", str(src), *extra, "-ac", "1", "-c:a", "libopus",
                    "-b:a", bitrate, str(dst)], check=True)
    return dst.read_bytes()


def _convert_on_kaggle(lines: list[LineAudio], ref: Path, options: dict, cfg: dict, work: Path, outs: list[Path]) -> None:
    sr = lines[0].sample_rate
    gap = np.zeros(int(GAP_S * sr), np.float32)
    chunks, bounds, cursor = [gap], [], len(gap)
    for l in lines:
        wav, _ = sf.read(l.wav_path, dtype="float32")
        bounds.append((cursor, cursor + len(wav)))
        chunks += [wav, gap]
        cursor += len(wav) + len(gap)
    joined = work / "vc_source.wav"
    sf.write(joined, np.concatenate(chunks), sr, subtype="PCM_16")

    ff = cfg["paths"]["ffmpeg"]
    inputs = {"source.ogg": base64.b64encode(_ogg(ff, joined, work / "vc_source.ogg", "48k")).decode(),
              "ref.ogg": base64.b64encode(_ogg(ff, ref, work / "vc_ref.ogg", "96k", ["-t", str(MAX_REF_S)])).decode(),
              **options}
    runner = RUNNER.read_text(encoding="utf-8")
    if "INPUTS = {}" not in runner:
        raise RuntimeError("Seed-VC runner template is missing its INPUTS marker")
    script = runner.replace("INPUTS = {}", "INPUTS = " + json.dumps(inputs), 1)
    if len(script) > 1_200_000:
        raise RuntimeError(f"too much audio for one Kaggle notebook ({len(script) // 1024} KB); use fewer/shorter lines")
    try:
        dest = kaggle_talk.run_kernel(KERNEL_SLUG, script, work, int(cfg["voice"].get("kaggle_timeout_min", 30)),
                                      doing="re-voicing")
    except kaggle_talk.KaggleUnavailable as e:
        # No quiet fallback to a different-sounding voice: stop with the reason.
        raise RuntimeError(f"The voice couldn't be converted on Kaggle: {e}") from e
    flac = dest / "converted.flac"
    if not flac.exists():
        raise RuntimeError(f"The Kaggle voice run finished without audio: {kaggle_talk._tail(dest)}")

    same_rate = work / "vc_converted.wav"  # back at the lines' own sample rate (proper resampling)
    subprocess.run([str(ff), "-y", "-loglevel", "error", "-i", str(flac), "-ac", "1", "-ar", str(sr), str(same_rate)],
                   check=True)
    out, _ = sf.read(same_rate, dtype="float32")
    # Seed-VC keeps the length (to within a few ms); map our cut points onto its timeline exactly
    ratio = len(out) / cursor
    if abs(ratio - 1) > 0.03:
        log.warning("  converted voice is %.1f%% %s than the original; captions may drift slightly",
                    abs(ratio - 1) * 100, "longer" if ratio > 1 else "shorter")
    for (a, b), path in zip(bounds, outs):
        seg = out[int(a * ratio): int(b * ratio)]
        want = b - a
        # exactly the line's original length, so its word timings stay valid
        seg = np.interp(np.linspace(0, len(seg) - 1, want), np.arange(len(seg)), seg).astype(np.float32)
        peak = float(np.max(np.abs(seg))) or 1.0
        tmp = path.with_suffix(".tmp.wav")
        sf.write(tmp, seg / peak * 0.9, sr, subtype="PCM_16")
        tmp.replace(path)
    log.info("  voice converted on Kaggle: %s", kaggle_talk._tail(dest))
