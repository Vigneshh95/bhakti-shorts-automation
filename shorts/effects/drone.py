"""A tanpura drone synthesised from scratch: no recording, so no music licence is needed.

The four strings are plucked in the classic Pa-Sa-Sa-sa cycle. Each pluck is a stack of decaying
harmonics with the tanpura's "jawari" shimmer (upper harmonics swell and fade slightly out of
step). The file is an exact whole number of cycles, and the ringing tails wrap from the end
back to the start, so it loops without a seam under a voice of any length."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def tanpura(out: Path, tonic_hz: float = 130.8, cycles: int = 9, pluck_s: float = 0.95, sr: int = 48000,
            seed: int = 3) -> Path:
    rng = np.random.default_rng(seed)
    strings = [tonic_hz * 0.75, tonic_hz, tonic_hz, tonic_hz * 0.5]   # Pa (below Sa), Sa, Sa, low Sa
    cycle = len(strings) * pluck_s
    n = int(round(cycles * cycle * sr))
    ring = int(6.0 * sr)                                                 # each pluck rings ~6 s
    t = np.arange(ring) / sr
    left, right = np.zeros(n + ring), np.zeros(n + ring)
    for c in range(cycles):
        for s, f0 in enumerate(strings):
            start = int(round((c * cycle + s * pluck_s) * sr))
            tone = np.zeros(ring)
            for k in range(1, 24):
                if f0 * k > 9000:
                    break
                decay = 3.2 / (1 + 0.12 * k)
                # jawari: harmonics bloom a moment after the pluck, each at its own pace
                bloom = 1 - np.exp(-t / (0.05 + 0.04 * k)) if k > 3 else 1.0
                shimmer = 1 + 0.25 * np.sin(2 * np.pi * (0.3 + 0.07 * k) * t + rng.uniform(0, 6.28))
                detune = 1 + rng.normal(0, 0.0004)
                tone += (k ** -0.9) * bloom * shimmer * np.exp(-t / decay) * np.sin(
                    2 * np.pi * f0 * k * detune * t + rng.uniform(0, 6.28))
            attack = np.minimum(1, t / 0.012)
            tone *= attack
            pan = 0.35 + 0.1 * s                                         # strings spread a little
            left[start:start + ring] += tone * (1 - pan)
            right[start:start + ring] += tone * pan
    # wrap the tails past the end onto the start: seamless loop
    left[:ring] += left[n:n + ring]
    right[:ring] += right[n:n + ring]
    stereo = np.stack([left[:n], right[:n]], axis=1)
    stereo /= np.max(np.abs(stereo)) / 0.5
    out.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf

    sf.write(out, stereo.astype(np.float32), sr, format="FLAC", subtype="PCM_16")
    return out
