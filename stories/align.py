"""Finds when each written word is spoken in a recording (for word-by-word captions), on this
machine's CPU: Meta's MMS forced aligner (1,100+ languages, works on romanised text).

The first use downloads the model (about 1.2 GB, kept by torch afterwards). It also gives a
clarity score: how confidently the written words are heard in the audio. A take in which the
voice said something else (rambled, read its directions aloud) scores low and is thrown away."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

_state: dict = {}


def _load():
    if not _state:
        import torch
        import torchaudio
        import uroman as ur

        bundle = torchaudio.pipelines.MMS_FA
        _state.update(torch=torch, torchaudio=torchaudio, bundle=bundle, model=bundle.get_model(with_star=False).eval(),
                      tokenizer=bundle.get_tokenizer(), align=bundle.get_aligner(), dict=bundle.get_dict(star=None),
                      uroman=ur.Uroman())
    return _state


def _romanise(word: str, st: dict) -> str:
    r = st["uroman"].romanize_string(word).lower()
    return "".join(ch for ch in r if ch in st["dict"] and ch != "-")


def word_times(wav_path: Path, words: list[str]) -> tuple[list[tuple[float, float]], float]:
    """((start, end) in seconds for every word, clarity score 0-1)."""
    st = _load()
    torch, torchaudio, bundle = st["torch"], st["torchaudio"], st["bundle"]
    wav, sr = sf.read(wav_path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    total = len(wav) / sr
    wave = torch.from_numpy(wav).unsqueeze(0)
    if sr != bundle.sample_rate:
        wave = torchaudio.functional.resample(wave, sr, bundle.sample_rate)
    roman = [_romanise(w, st) for w in words]
    idx = [i for i, r in enumerate(roman) if r]
    if not idx:
        return _fill([None] * len(words), words, total), 0.0
    with torch.inference_mode():
        emission, _ = st["model"](wave)
    try:
        spans = st["align"](emission[0], st["tokenizer"]([roman[i] for i in idx]))
    except Exception:  # noqa: BLE001 -- the audio is too short for the text: not a usable take
        return _fill([None] * len(words), words, total), 0.0
    ratio = wave.shape[1] / emission.shape[1] / bundle.sample_rate
    out, scores = [None] * len(words), []
    for i, s in zip(idx, spans):
        out[i] = (s[0].start * ratio, s[-1].end * ratio)
        scores += [float(tok.score) for tok in s]
    return _fill(out, words, total), float(np.mean(scores)) if scores else 0.0


def _fill(times: list, words: list[str], total: float) -> list[tuple[float, float]]:
    """Words the aligner couldn't place share the time between their placed neighbours."""
    times, i = list(times), 0
    while i < len(times):
        if times[i] is None:
            j = i
            while j < len(times) and times[j] is None:
                j += 1
            start = times[i - 1][1] if i > 0 else 0.0
            end = times[j][0] if j < len(times) else total
            weights = np.array([max(1, len(w)) for w in words[i:j]], float)
            edges = start + np.concatenate([[0], np.cumsum(weights / weights.sum())]) * max(0.0, end - start)
            for k in range(i, j):
                times[k] = (float(edges[k - i]), float(edges[k - i + 1]))
            i = j
        else:
            i += 1
    return times
