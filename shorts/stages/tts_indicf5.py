"""TTS stage, voice-cloning engine ([voice] engine = "indicf5"): every line is spoken in the
voice of a reference recording by IndicF5 on your free Kaggle GPU, with word timings from a
forced aligner in the same run (shorts/vendor/kaggle_indicf5.py).

Returns the same LineAudio list as the FastPitch stage, so the audio mix, captions and talking
face work unchanged. Lines are cached one by one (text + reference voice), so a re-run, or a
day whose lines were already spoken, never goes back to Kaggle.

The reference: [voice] reference = "voices/periyava_ref.wav" (10-20 s of clear speech, no
music) with its exact words in the .txt file of the same name."""
from __future__ import annotations

import base64
import json
import subprocess
import zipfile
from pathlib import Path

from shorts.cache import Cache, file_digest
from shorts.config import ROOT
from shorts.log import log
from shorts.stages import kaggle_talk
from shorts.stages.tts import LineAudio, Word, _snap_first_word_to_onset

VERSION = "1"
RUNNER = ROOT / "shorts" / "vendor" / "kaggle_indicf5.py"
KERNEL_SLUG = "periyava-voice"
MAX_REF_S = 15  # IndicF5 copies the voice from the first seconds; a longer reference only slows it


def reference(cfg: dict) -> tuple[Path, str]:
    ref = Path(cfg["voice"]["reference"])
    ref = ref if ref.is_absolute() else ROOT / ref
    text_file = ref.with_suffix(".txt")
    if not ref.exists():
        raise FileNotFoundError(f"Voice sample missing: put 10-20 s of clear speech at {ref}")
    if not text_file.exists() or not text_file.read_text(encoding="utf-8").strip():
        raise FileNotFoundError(f"Write the exact words of the voice sample into {text_file}")
    return ref, text_file.read_text(encoding="utf-8").strip()


def _options(cfg: dict) -> dict:
    """How IndicF5 speaks: pace, how many takes per line (the clearest is kept), and quality."""
    v = cfg["voice"]
    return {"speed": float(v.get("speak_speed", 1.0)), "takes": int(v.get("speak_takes", 1)),
            "steps": int(v.get("speak_steps", 32)), "cfg": float(v.get("speak_cfg", 2.0))}


def synthesize_lines(lines: list[str], cfg: dict, cache: Cache, work: Path) -> list[LineAudio]:
    ref, ref_text = reference(cfg)
    signature = [VERSION, file_digest(ref), ref_text, _options(cfg)]
    keys = [cache.key("tts_f5", text, signature) for text in lines]
    paths = [cache.lookup("tts_f5", k, ".wav") for k in keys]
    todo = [i for i, (p, hit) in enumerate(paths) if not (hit and p.with_suffix(".json").exists())]
    if todo:
        log.info("  speaking %d line(s) in the reference voice on your Kaggle GPU (IndicF5)…", len(todo))
        _speak_on_kaggle([lines[i] for i in todo], ref, ref_text, cfg, work, [paths[i][0] for i in todo])
    else:
        log.info("  all %d lines cached", len(lines))

    results = []
    for text, (wav_path, _) in zip(lines, paths):
        meta = json.loads(wav_path.with_suffix(".json").read_text(encoding="utf-8"))
        words = [Word(t, s, e) for t, s, e in meta["words"]]
        _snap_first_word_to_onset(words, wav_path)
        results.append(LineAudio(text, wav_path, meta["sample_rate"], meta["duration"], words))
    return results


def tighten(wav_path: Path, lead_s: float = 0.12, tail_s: float = 0.40) -> None:
    """Trims a spoken line to its words: it starts just before the first word and ends a little
    after the last (keeping the voice's natural trailing-off, eased out). The model sometimes
    leaves a second or two of faint hiss around the speech, which would sound like odd gaps."""
    import numpy as np
    import soundfile as sf

    meta_path = wav_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta.get("words"):
        return
    wav, sr = sf.read(wav_path, dtype="float32")
    start = max(0.0, meta["words"][0][1] - lead_s)
    end = min(len(wav) / sr, meta["words"][-1][2] + tail_s)
    seg = wav[int(start * sr): int(end * sr)].copy()
    fade_in, fade_out = min(len(seg), int(0.02 * sr)), min(len(seg), int(0.15 * sr))
    seg[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    seg[-fade_out:] *= np.linspace(1.0, 0.0, fade_out) ** 2
    sf.write(wav_path, seg, sr, subtype="PCM_16")
    meta["words"] = [[w, max(0.0, s - start), max(0.0, e - start)] for w, s, e in meta["words"]]
    meta["duration"] = len(seg) / sr
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _speak_on_kaggle(lines: list[str], ref: Path, ref_text: str, cfg: dict, work: Path, outs: list[Path]) -> None:
    flac = work / "voice_reference.flac"
    # Mono 24 kHz (IndicF5's rate), the first MAX_REF_S seconds, lightly denoised: old recordings
    # hiss, and the model would copy the hiss along with the voice.
    af = "afftdn=nf=-25," if cfg["voice"].get("reference_denoise", True) else ""
    subprocess.run([str(cfg["paths"]["ffmpeg"]), "-y", "-loglevel", "error", "-i", str(ref), "-t", str(MAX_REF_S),
                    "-af", af + "loudnorm=I=-20:TP=-2", "-ac", "1", "-ar", "24000", "-c:a", "flac", str(flac)],
                   check=True)
    inputs = {"ref.flac": base64.b64encode(flac.read_bytes()).decode(), "ref_text": ref_text, "lines": lines,
              **_options(cfg)}
    from autopilot.settings import api_key

    token = api_key("HF_TOKEN")  # a line HF_TOKEN=... in .env; goes only into your PRIVATE Kaggle notebook.
    if token:                    # (Without it, the notebook looks for a Kaggle secret named HF_TOKEN.)
        inputs["hf_token"] = token
    runner = RUNNER.read_text(encoding="utf-8")
    if "INPUTS = {}" not in runner:
        raise RuntimeError("IndicF5 runner template is missing its INPUTS marker")
    script = runner.replace("INPUTS = {}", "INPUTS = " + json.dumps(inputs, ensure_ascii=False), 1)
    if len(script.encode("utf-8")) > 900_000:
        raise RuntimeError("the voice sample is too large for a Kaggle notebook; use a shorter clip (10-15 s)")
    try:
        dest = kaggle_talk.run_kernel(KERNEL_SLUG, script, work, int(cfg["voice"].get("kaggle_timeout_min", 30)),
                                      doing="speaking")
    except kaggle_talk.KaggleUnavailable as e:
        # No quiet fallback to a different voice: a series with a set voice stops with the reason.
        raise RuntimeError(f"The voice couldn't be made on Kaggle: {e}") from e
    archive = dest / "voice.zip"
    if not archive.exists():
        raise RuntimeError(f"The Kaggle voice run finished without audio: {kaggle_talk._tail(dest)}")
    with zipfile.ZipFile(archive) as z:
        for n, out in enumerate(outs, 1):
            out.write_bytes(z.read(f"line_{n:02d}.wav"))
            out.with_suffix(".json").write_bytes(z.read(f"line_{n:02d}.json"))
            tighten(out)
    log.info("  voice made on Kaggle: %s", kaggle_talk._tail(dest))
