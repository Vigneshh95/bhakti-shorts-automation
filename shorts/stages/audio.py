"""Audio stage: stitch the cached TTS lines, apply the voice style, add background music
with automatic ducking, and measure loudness -- in ONE ffmpeg filtergraph instead of the
old chain of 5+ separate ffmpeg/pydub calls each writing a temp WAV.

Loudness is two-pass EBU R128: this stage measures the mix; the render stage applies the
measured correction while muxing, so the mix is never re-encoded an extra time."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from shorts import ffmpeg
from shorts.stages.tts import LineAudio


@dataclass
class TimedWord:
    text: str
    start: float  # seconds on the FINAL video timeline
    end: float
    line: int


@dataclass
class AudioResult:
    mix_path: Path
    duration: float
    words: list[TimedWord]
    line_spans: list[tuple[float, float]]  # (start, end) of each spoken line on the final timeline
    loudnorm_filter: str  # second-pass loudnorm with the measured values baked in
    voice_path: Path | None = None  # processed voice alone, same timeline (drives the talking head)


def build_voice_track(lines: list[LineAudio], voice_cfg: dict, pace: float, out_path: Path):
    """Concatenates the lines with the configured pauses (in the PRE-pace timeline) and
    returns word/line timings already mapped onto the final, paced timeline."""
    sr = lines[0].sample_rate
    # Silences are stretched by the pace filter along with the speech, so they're written
    # pre-divided to land at exactly the configured length in the final audio.
    lead = int(voice_cfg["lead_in_ms"] / 1000 * pace * sr)
    gap = int(voice_cfg["line_gap_ms"] / 1000 * pace * sr)
    tail = int(voice_cfg["tail_ms"] / 1000 * pace * sr)

    chunks, words, spans = [np.zeros(lead, np.float32)], [], []
    cursor = lead
    for i, line in enumerate(lines):
        wav, _ = sf.read(line.wav_path, dtype="float32")
        start = cursor / sr
        for w in line.words:
            words.append(TimedWord(w.text, (start + w.start) / pace, (start + w.end) / pace, i))
        spans.append((start / pace, (start + len(wav) / sr) / pace))
        chunks.append(wav)
        cursor += len(wav)
        pad = gap if i < len(lines) - 1 else tail
        chunks.append(np.zeros(pad, np.float32))
        cursor += pad

    voice = np.concatenate(chunks)
    peak = float(np.max(np.abs(voice))) or 1.0
    sf.write(out_path, voice / peak * 0.9, sr, subtype="PCM_16")
    return len(voice) / sr / pace, words, spans


def voice_filter(style: dict, sample_rate: int) -> str:
    pitch = 2 ** (style["semitones"] / 12)
    parts = [f"aresample={sample_rate}"]
    if abs(pitch - 1) > 1e-3 or abs(style["pace"] - 1) > 1e-3:
        parts.append(f"rubberband=pitch={pitch:.5f}:tempo={style['pace']:.5f}:formant={style['formant']}:pitchq=quality")
    parts.append("highpass=f=70")
    if style.get("eq_gain_db"):
        parts.append(f"equalizer=f=4000:t=q:w=0.7:g={style['eq_gain_db']}")
    if style.get("warmth_db"):  # a little more body in the low-mids: an old, gentle voice
        parts.append(f"equalizer=f=220:t=q:w=1.0:g={style['warmth_db']}")
    if style.get("compress"):
        parts.append("acompressor=threshold=-18dB:ratio=3:attack=5:release=200:makeup=4")
    if style.get("hall"):  # soft temple-hall echo: two faint early reflections, speech stays clear
        amount = float(style["hall"])
        parts.append(f"aecho=0.9:0.9:45|95:{0.30 * amount:.3f}|{0.18 * amount:.3f}")
    return ",".join(parts)


def make_audio(lines: list[LineAudio], cfg: dict, work: Path) -> AudioResult:
    ff, audio_cfg, voice_cfg = cfg["paths"]["ffmpeg"], cfg["audio"], cfg["voice"]
    style = voice_cfg["styles"][voice_cfg["style"]]
    sr = audio_cfg["sample_rate"]

    raw = work / "voice_raw.wav"
    duration, words, spans = build_voice_track(lines, voice_cfg, style["pace"], raw)

    bgm = cfg["paths"].get("bgm")
    mix = work / "mix.wav"
    vf = voice_filter(style, sr)
    if bgm and bgm.exists():
        fade = audio_cfg["bgm_fade_s"]
        music = (f"[1:a]aresample={sr},volume={audio_cfg['bgm_db']}dB,"
                 f"afade=t=in:d={fade},afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade}[bg]")
        if audio_cfg["duck"]:
            graph = (f"[0:a]{vf},asplit=2[v][key];{music};"
                     "[bg][key]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400:makeup=1[ducked];"
                     "[v][ducked]amix=inputs=2:duration=first:normalize=0[out]")
        else:
            graph = f"[0:a]{vf}[v];{music};[v][bg]amix=inputs=2:duration=first:normalize=0[out]"
        args = ["-i", str(raw), "-stream_loop", "-1", "-i", str(bgm), "-filter_complex", graph, "-map", "[out]"]
    else:
        args = ["-i", str(raw), "-af", vf]
    ffmpeg.run(ff, [*args, "-t", f"{duration:.3f}", "-ac", "2", "-c:a", "pcm_f32le", str(mix)])

    voice_only = None
    if cfg.get("talking", {}).get("enabled"):
        # SadTalker reads 16 kHz mono; music would only confuse the lip movements
        voice_only = work / "voice_16k.wav"
        ffmpeg.run(ff, ["-i", str(raw), "-af", vf, "-t", f"{duration:.3f}", "-ac", "1", "-ar", "16000", str(voice_only)])
    return AudioResult(mix, duration, words, spans, _measure_loudnorm(ff, mix, audio_cfg), voice_only)


def _measure_loudnorm(ff: Path, mix: Path, audio_cfg: dict) -> str:
    target = f"I={audio_cfg['target_lufs']}:TP={audio_cfg['true_peak_db']}:LRA=11"
    stderr = ffmpeg.run(ff, ["-i", str(mix), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-"])
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S).group(0))
    return (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
