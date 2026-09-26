import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shorts.config import load_config  # noqa: E402
from shorts.stages.tts import Word  # noqa: E402


@pytest.fixture
def cfg():
    return load_config()


class FakeVoice:
    """Stands in for FastPitch: a soft tone per word with exact, known word timings, so
    tests exercise everything downstream without loading the 1.6 GB model."""

    def __init__(self, *_, **__):
        self.calls = 0

    def model_signature(self):
        return ["fake-voice-v1"]

    def synthesize(self, text, speaker):
        self.calls += 1
        sr, words, t, chunks = 22050, [], 0.0, []
        for w in text.split():
            d = 0.12 + 0.05 * len(w)
            n = int(d * sr)
            chunks.append(0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / sr).astype(np.float32))
            words.append(Word(w, t, t + d))
            t += d
            gap = int(0.08 * sr)
            chunks.append(np.zeros(gap, np.float32))
            t += gap / sr
        return np.concatenate(chunks), sr, words


@pytest.fixture
def fake_voice():
    return FakeVoice()
