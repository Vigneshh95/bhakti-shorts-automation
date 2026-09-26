"""TTS stage: IndicTTS FastPitch + HiFi-GAN (the voice already in use), one speaker only,
with exact per-word timings taken from the model's own duration predictions.

FastPitch predicts how many mel frames each input character lasts; this model takes raw
characters (no phonemes, no blank tokens), so summing those durations over a word's
characters gives that word's start/end time. That's what drives the word-highlight
captions -- no separate speech-alignment model is needed.

Each line is cached on its own (text + speaker + model identity), so editing one line
re-synthesizes only that line, and a fully-cached episode never loads the model at all."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from shorts.cache import Cache
from shorts.log import log

TTS_VERSION = "1"  # bump to invalidate cached lines if the synthesis code changes


@dataclass
class Word:
    text: str
    start: float  # seconds, relative to the line's own audio
    end: float


@dataclass
class LineAudio:
    text: str
    wav_path: Path
    sample_rate: int
    duration: float
    words: list[Word] = field(default_factory=list)


class FastPitchVoice:
    """Loaded lazily -- importing torch + TTS and loading ~1.6 GB of checkpoints takes
    ~25 s and ~1.2 GB RAM, which is wasted when every line is already cached."""

    def __init__(self, checkpoints: Path, threads: int):
        self.checkpoints = checkpoints
        self.threads = threads
        self._synth = None

    def model_signature(self) -> list:
        files = ["fastpitch/best_model.pth", "fastpitch/config.json", "fastpitch/speakers.pth",
                 "hifigan/best_model.pth", "hifigan/config.json"]
        sig = []
        for rel in files:
            p = self.checkpoints / rel
            if not p.exists():
                raise FileNotFoundError(f"Missing TTS checkpoint: {p}")
            st = p.stat()
            sig.append([rel, st.st_size, int(st.st_mtime)])
        return sig

    def _load(self):
        if self._synth is not None:
            return self._synth
        log.info("  loading IndicTTS FastPitch + HiFi-GAN (first uncached line)…")
        import torch
        from TTS.utils.synthesizer import Synthesizer

        torch.set_num_threads(self.threads)
        c = self.checkpoints
        self._synth = Synthesizer(
            tts_checkpoint=str(c / "fastpitch/best_model.pth"),
            tts_config_path=str(c / "fastpitch/config.json"),
            tts_speakers_file=str(c / "fastpitch/speakers.pth"),
            vocoder_checkpoint=str(c / "hifigan/best_model.pth"),
            vocoder_config=str(c / "hifigan/config.json"),
            use_cuda=False,
        )
        return self._synth

    def synthesize(self, text: str, speaker: str) -> tuple[np.ndarray, int, list[Word]]:
        import torch
        from TTS.tts.utils.synthesis import synthesis, trim_silence

        synth = self._load()
        model = synth.tts_model
        speaker_id = model.speaker_manager.name_to_id[speaker]

        with torch.inference_mode():
            out = synthesis(model=model, text=text, CONFIG=synth.tts_config, use_cuda=False, speaker_id=speaker_id)
            mel = out["outputs"]["model_outputs"][0].detach().cpu().numpy()
            mel = model.ap.denormalize(mel.T).T
            vocoder_input = torch.tensor(synth.vocoder_ap.normalize(mel.T)).unsqueeze(0)
            wav = synth.vocoder_model.inference(vocoder_input).cpu().numpy().squeeze()

        # Same end-of-clip trim the stock Synthesizer applies (it only trims the END, so
        # word start times are unaffected).
        if synth.tts_config.audio.get("do_trim_silence"):
            wav = trim_silence(wav, model.ap)

        sr = int(model.ap.sample_rate)
        hop = int(model.ap.hop_length)
        frames = _frames_per_token(out["alignments"], out["text_inputs"].shape[-1])
        words = _word_timings(model.tokenizer, text, frames, hop / sr, len(wav) / sr)
        return wav.astype(np.float32), sr, words


def _frames_per_token(alignments, n_tokens: int) -> np.ndarray:
    a = alignments[0].detach().cpu().numpy() if hasattr(alignments, "detach") else np.asarray(alignments[0])
    a = np.squeeze(a)
    # attention is [T_en, T_de] or [T_de, T_en]; sum over the decoder (mel frame) axis
    axis = 1 if a.shape[0] == n_tokens else 0
    return a.sum(axis=axis)


def _word_timings(tokenizer, text: str, frames: np.ndarray, sec_per_frame: float, total: float) -> list[Word]:
    """Maps per-token durations back to the words of the ORIGINAL text (with its
    punctuation, for display). Falls back to splitting the line's time proportionally by
    character count if the tokenizer's cleaning changed the word structure."""
    display_words = text.split()
    cleaned = tokenizer.text_cleaner(text) if getattr(tokenizer, "text_cleaner", None) else text

    token_idx = 0
    token_spans: list[tuple[int, int]] = []  # [first, last] token of each word
    current: list[int] = []
    for ch in cleaned:
        n = len(tokenizer.encode(ch))  # 0 if the tokenizer drops this character
        if ch == " ":
            if current:
                token_spans.append((current[0], current[-1]))
                current = []
            token_idx += n  # the space token (if in vocab) belongs to no word
            continue
        current.extend(range(token_idx, token_idx + n))
        token_idx += n
    if current:
        token_spans.append((current[0], current[-1]))

    if len(token_spans) != len(display_words) or token_idx != len(frames):
        log.debug("word timing fallback for %r (%d spans vs %d words, %d tokens vs %d durations)",
                  text, len(token_spans), len(display_words), token_idx, len(frames))
        weights = np.array([len(w) for w in display_words], dtype=float)
        edges = np.concatenate([[0.0], np.cumsum(weights / weights.sum())]) * total
        return [Word(w, float(edges[i]), float(edges[i + 1])) for i, w in enumerate(display_words)]

    starts = np.concatenate([[0.0], np.cumsum(frames)]) * sec_per_frame
    return [Word(w, float(starts[a]), float(min(starts[b + 1], total))) for w, (a, b) in zip(display_words, token_spans)]


def synthesize_lines(lines: list[str], speaker: str, voice: FastPitchVoice, cache: Cache) -> list[LineAudio]:
    signature = voice.model_signature()
    results = []
    for i, text in enumerate(lines, 1):
        key = cache.key("tts", TTS_VERSION, text, speaker, signature)
        wav_path, hit = cache.lookup("tts", key, ".wav")
        meta_path = wav_path.with_suffix(".json")
        if hit and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            log.info("  line %d/%d cached", i, len(lines))
        else:
            log.info("  line %d/%d synthesizing: %s", i, len(lines), text)
            wav, sr, words = voice.synthesize(text, speaker)
            tmp = wav_path.with_suffix(".tmp.wav")
            sf.write(tmp, wav, sr, subtype="PCM_16")
            os.replace(tmp, wav_path)
            meta = {"sample_rate": sr, "duration": len(wav) / sr,
                    "words": [[w.text, w.start, w.end] for w in words]}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        results.append(LineAudio(
            text=text, wav_path=wav_path, sample_rate=meta["sample_rate"], duration=meta["duration"],
            words=[Word(t, s, e) for t, s, e in meta["words"]],
        ))
    return results
