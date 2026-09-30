"""Runs ON KAGGLE (free GPU), pushed there by shorts/stages/tts_indicf5.py.

Speaks each line in the voice of a reference recording with IndicF5 (AI4Bharat, MIT licence;
Tamil and 10 other Indian languages), then finds when each word is spoken with a forced
aligner (torchaudio's MMS model, via romanised text), for the word-by-word captions.

Inputs (embedded below by tts_indicf5.py): the reference recording (FLAC) and its exact words,
and the lines to speak. IndicF5 is gated on Hugging Face: the notebook reads a Kaggle secret
HF_TOKEN (Add-ons > Secrets in the notebook editor), so no token is ever in this code.
Output in /kaggle/working: voice.zip (line_01.wav + line_01.json …) and run_log.txt."""
import base64
import json
import os
import subprocess
import sys
import time
import zipfile

INPUTS = {}  # filled in by tts_indicf5.py: {"ref.flac": "<base64>", "ref_text": "...", "lines": ["...", ...]}

T0 = time.time()
OUT = "/kaggle/working"
LOG = open(os.path.join(OUT, "run_log.txt"), "w")


def log(*parts):
    line = f"[{time.time() - T0:6.1f}s] " + " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log(res.stdout[-2000:], res.stderr[-2000:])
        raise SystemExit(f"command failed: {' '.join(cmd[:4])}")


import socket  # noqa: E402

try:
    socket.gethostbyname("huggingface.co")
except OSError:
    raise SystemExit("NO INTERNET on Kaggle: verify your phone number at kaggle.com/settings")

try:
    from kaggle_secrets import UserSecretsClient

    token = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:  # noqa: BLE001
    token = os.environ.get("HF_TOKEN", "")
if not token:
    raise SystemExit("NO HF_TOKEN: add your Hugging Face token as a secret named HF_TOKEN to the Kaggle notebook "
                     "'periyava-voice' (open it on kaggle.com > Edit > Add-ons > Secrets), after accepting the "
                     "terms at huggingface.co/ai4bharat/IndicF5")
os.environ["HF_TOKEN"] = token

os.makedirs("/tmp/in", exist_ok=True)
REF = "/tmp/in/ref.flac"
with open(REF, "wb") as f:
    f.write(base64.b64decode(INPUTS["ref.flac"]))

run([sys.executable, "-m", "pip", "install", "-q", "git+https://github.com/ai4bharat/IndicF5.git", "uroman", "soundfile"])
log("packages ready")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
import torchaudio  # noqa: E402
from transformers import AutoModel  # noqa: E402

log("GPU:", torch.cuda.get_device_name(0))
ref_wav = "/tmp/in/ref.wav"
audio, sr = sf.read(REF, dtype="float32")
sf.write(ref_wav, audio, sr)
model = AutoModel.from_pretrained("ai4bharat/IndicF5", trust_remote_code=True, token=token)
model = model.to("cuda")
log("IndicF5 ready")

# --- forced aligner (MMS, trained on 1,100+ languages; works on romanised text) ---
import uroman as ur  # noqa: E402

bundle = torchaudio.pipelines.MMS_FA
aligner = bundle.get_model(with_star=False).to("cuda")
tokenizer, align = bundle.get_tokenizer(), bundle.get_aligner()
DICT = bundle.get_dict(star=None)
uroman = ur.Uroman()


def romanise(word):
    r = uroman.romanize_string(word).lower()
    return "".join(ch for ch in r if ch in DICT and ch != "-")


def word_times(wav, sr, words):
    """(start, end) seconds of each word; None where a word can't be aligned."""
    wave = torch.from_numpy(wav).unsqueeze(0)
    if sr != bundle.sample_rate:
        wave = torchaudio.functional.resample(wave, sr, bundle.sample_rate)
    roman = [romanise(w) for w in words]
    idx = [i for i, r in enumerate(roman) if r]
    if not idx:
        return [None] * len(words)
    with torch.inference_mode():
        emission, _ = aligner(wave.to("cuda"))
    spans = align(emission[0], tokenizer([roman[i] for i in idx]))
    ratio = wave.shape[1] / emission.shape[1] / bundle.sample_rate
    out = [None] * len(words)
    for i, s in zip(idx, spans):
        out[i] = (s[0].start * ratio, s[-1].end * ratio)
    return out


def fill_gaps(times, words, total):
    """Words the aligner couldn't place share the time between their aligned neighbours."""
    times = list(times)
    i = 0
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


def trim(wav, sr, db=-40.0, pad=0.08):
    """Cut leading/trailing silence, keeping a short natural margin."""
    frame = int(sr * 0.01)
    n = len(wav) // frame
    rms = np.sqrt((wav[: n * frame].reshape(n, frame) ** 2).mean(axis=1) + 1e-12)
    loud = np.nonzero(rms > rms.max() * 10 ** (db / 20))[0]
    if not len(loud):
        return wav
    a = max(0, loud[0] * frame - int(pad * sr))
    b = min(len(wav), (loud[-1] + 1) * frame + int(pad * sr))
    return wav[a:b]


folder = "/tmp/voice"
os.makedirs(folder, exist_ok=True)
for n, text in enumerate(INPUTS["lines"], 1):
    t = time.time()
    wav = model(text, ref_audio_path=ref_wav, ref_text=INPUTS["ref_text"])
    wav = np.asarray(wav)
    if wav.dtype == np.int16:
        wav = wav.astype(np.float32) / 32768.0
    wav = trim(wav.astype(np.float32).squeeze(), 24000)
    words = text.split()
    times = fill_gaps(word_times(wav, 24000, [w.strip(".,;:!?") for w in words]), words, len(wav) / 24000)
    sf.write(os.path.join(folder, f"line_{n:02d}.wav"), wav, 24000, subtype="PCM_16")
    with open(os.path.join(folder, f"line_{n:02d}.json"), "w", encoding="utf-8") as f:
        json.dump({"text": text, "sample_rate": 24000, "duration": len(wav) / 24000,
                   "words": [[w, s, e] for w, (s, e) in zip(words, times)]}, f, ensure_ascii=False)
    log(f"line {n}/{len(INPUTS['lines'])}: {len(wav) / 24000:.1f} s ({time.time() - t:.0f} s)")

with zipfile.ZipFile(os.path.join(OUT, "voice.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for name in sorted(os.listdir(folder)):
        z.write(os.path.join(folder, name), name)
log(f"done in {time.time() - T0:.0f} s")
