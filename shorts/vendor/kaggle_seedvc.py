"""Runs ON KAGGLE (free GPU), pushed there by shorts/stages/voice_convert.py.

Voice conversion with Seed-VC (zero-shot: no training, no sign-in): the source speech (clear
Tamil from the laptop's own voice) is re-voiced in the timbre of a short reference recording.
The words and their timing stay as they are, so the captions' word timings remain valid.

Inputs (embedded below): source.ogg (all lines, joined) and ref.ogg (the reference voice).
Output in /kaggle/working: converted.flac and run_log.txt."""
import base64
import glob
import os
import shutil
import subprocess
import sys
import time

INPUTS = {}  # filled in by voice_convert.py: {"source.ogg": "<base64>", "ref.ogg": "<base64>", "steps": 30, "cfg": 0.7}

T0 = time.time()
OUT = "/kaggle/working"
LOG = open(os.path.join(OUT, "run_log.txt"), "w")


def log(*parts):
    line = f"[{time.time() - T0:6.1f}s] " + " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def run(cmd, **kw):
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if res.returncode != 0:
        log(res.stdout[-2500:], res.stderr[-2500:])
        raise SystemExit(f"command failed: {' '.join(cmd[:4])}")
    return res


import socket  # noqa: E402

try:
    socket.gethostbyname("huggingface.co")
except OSError:
    raise SystemExit("NO INTERNET on Kaggle: verify your phone number at kaggle.com/settings")

IN = "/tmp/in"
os.makedirs(IN, exist_ok=True)
for name in ("source.ogg", "ref.ogg"):
    with open(os.path.join(IN, name), "wb") as f:
        f.write(base64.b64decode(INPUTS[name]))

WORK = "/tmp/seed-vc"
shutil.rmtree(WORK, ignore_errors=True)
run(["git", "clone", "--depth", "1", "https://github.com/Plachtaa/seed-vc.git", WORK])
# Seed-VC's vocoder loader was written for an older huggingface_hub: the current one no longer
# passes (or accepts) `proxies` / `resume_download`. Same behaviour without them.
vocoder = os.path.join(WORK, "modules/bigvgan/bigvgan.py")
src = open(vocoder, encoding="utf-8").read()
src = src.replace("proxies: Optional[Dict],", "proxies: Optional[Dict] = None,")
src = src.replace("resume_download: bool,", "resume_download: bool = False,")
src = src.replace("                proxies=proxies,\n", "").replace("                resume_download=resume_download,\n", "")
open(vocoder, "w", encoding="utf-8").write(src)
# Kaggle's own CUDA torch/torchaudio/transformers/librosa are kept; only what's missing is added.
run([sys.executable, "-m", "pip", "install", "-q", "munch", "einops", "descript-audio-codec", "hydra-core",
     "pydub", "resemblyzer", "soundfile", "python-dotenv", "imageio-ffmpeg"])
log("packages ready")

ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
for name in ("source", "ref"):
    run([ffmpeg, "-y", "-loglevel", "error", "-i", f"{IN}/{name}.ogg", "-ac", "1", "-ar", "44100", f"{IN}/{name}.wav"])

result = "/tmp/result"
shutil.rmtree(result, ignore_errors=True)
t = time.time()
run([sys.executable, "inference.py", "--source", f"{IN}/source.wav", "--target", f"{IN}/ref.wav", "--output", result,
     "--diffusion-steps", str(INPUTS.get("steps", 30)), "--length-adjust", "1.0",
     "--inference-cfg-rate", str(INPUTS.get("cfg", 0.7)), "--fp16", "True"], cwd=WORK)
wavs = sorted(glob.glob(os.path.join(result, "*.wav")), key=os.path.getmtime)
if not wavs:
    raise SystemExit("Seed-VC produced no audio")
run([ffmpeg, "-y", "-loglevel", "error", "-i", wavs[-1], "-ac", "1", "-c:a", "flac", os.path.join(OUT, "converted.flac")])
log(f"voice converted in {time.time() - t:.0f} s (total {time.time() - T0:.0f} s)")
