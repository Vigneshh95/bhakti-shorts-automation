"""Runs ON KAGGLE (free GPU), pushed there by shorts/stages/kaggle_talk.py.

Inputs: today's picture and voice are embedded below (INPUTS, base64) by kaggle_talk.py, and
SadTalker's code is cloned from its official GitHub repository. (Kaggle datasets aren't used:
new-style API tokens can run notebooks but may not be allowed to manage private datasets.)
Output (the only file left in /kaggle/working, so the download stays small):
  talking.mp4, run_log.txt

SadTalker's model files are downloaded here from the official GitHub releases (fast on
Kaggle's network), and its Python packages are pinned to the versions that work locally."""
import concurrent.futures as cf
import glob
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import base64
import zipfile

INPUTS = {}  # filled in by kaggle_talk.py: {"face.jpg": "<base64>", "voice.ogg": "<base64>"}
# (Kaggle rejects notebooks of ~2 MB, so only a crop around the face and a compressed voice are sent;
#  the laptop blends the animated face back into the full-resolution picture.)

T0 = time.time()
WORK = "/tmp/sadtalker"
OUT = "/kaggle/working"
LOG = open(os.path.join(OUT, "run_log.txt"), "w")


def log(*parts):
    line = f"[{time.time() - T0:6.1f}s] " + " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def run(cmd, **kw):
    log("$", " ".join(cmd) if isinstance(cmd, list) else cmd)
    res = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if res.returncode != 0:
        log(res.stdout[-3000:], res.stderr[-3000:])
        raise SystemExit(f"command failed ({res.returncode})")
    return res.stdout


IN = "/tmp/in"
os.makedirs(IN, exist_ok=True)
for name, data in INPUTS.items():
    with open(os.path.join(IN, name), "wb") as f:
        f.write(base64.b64decode(data))


def find(name):
    return os.path.join(IN, name)


# 0) Kaggle only provides internet and a GPU on phone-verified accounts; say so plainly
import socket  # noqa: E402

try:
    socket.gethostbyname("github.com")
except OSError:
    raise SystemExit("NO INTERNET on Kaggle: verify your phone number at kaggle.com/settings "
                     "(Kaggle gives internet and GPUs only to phone-verified accounts)")
log("internet ok")

# 1) SadTalker code, from the official repository
shutil.rmtree(WORK, ignore_errors=True)
run(["git", "clone", "--depth", "1", "https://github.com/OpenTalker/SadTalker.git", WORK])
log("code ready")

# 2) model files, in parallel, from the official releases
FILES = {
    "checkpoints/mapping_00109-model.pth.tar": "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00109-model.pth.tar",
    "checkpoints/mapping_00229-model.pth.tar": "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/mapping_00229-model.pth.tar",
    "checkpoints/SadTalker_V0.0.2_256.safetensors": "https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc/SadTalker_V0.0.2_256.safetensors",
    "gfpgan/weights/alignment_WFLW_4HG.pth": "https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth",
    "gfpgan/weights/detection_Resnet50_Final.pth": "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth",
}


def fetch(item):
    rel, url = item
    dest = os.path.join(WORK, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(3):
        try:
            urllib.request.urlretrieve(url, dest)
            return rel, os.path.getsize(dest)
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(5)


with cf.ThreadPoolExecutor(5) as pool:
    for rel, size in pool.map(fetch, FILES.items()):
        log(f"downloaded {rel} ({size / 1e6:.0f} MB)")

# 3) Python packages: the versions SadTalker runs with on the laptop (Kaggle keeps its CUDA torch)
run([sys.executable, "-m", "pip", "install", "-q", "numpy==1.26.4", "face-alignment==1.3.5", "facexlib==0.3.0",
     "gfpgan==1.3.8", "basicsr==1.4.2", "kornia==0.6.8", "librosa==0.9.2", "resampy==0.3.1", "yacs==0.1.8",
     "pydub==0.25.1", "imageio-ffmpeg==0.4.7", "safetensors", "av"])
# basicsr imports a torchvision module that newer torchvision renamed
for f in glob.glob("/usr/local/lib/python3*/*-packages/basicsr/data/degradations.py") + \
        glob.glob(os.path.join(sys.prefix, "lib/python3*/site-packages/basicsr/data/degradations.py")):
    src = open(f).read().replace("torchvision.transforms.functional_tensor", "torchvision.transforms.functional")
    open(f, "w").write(src)
log("packages ready")
run([sys.executable, "-c", "import torch; print('GPU:', torch.cuda.get_device_name(0))"])

# the voice arrives compressed (Opus); SadTalker wants plain 16 kHz WAV
ffmpeg = shutil.which("ffmpeg")
if not ffmpeg:
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
run([ffmpeg, "-y", "-loglevel", "error", "-i", find("voice.ogg"), "-ac", "1", "-ar", "16000", find("voice_16k.wav")])

# 4) animate
result_dir = "/tmp/result"
shutil.rmtree(result_dir, ignore_errors=True)
args = [sys.executable, "inference.py", "--driven_audio", find("voice_16k.wav"), "--source_image", find("face.jpg"),
        "--result_dir", result_dir, "--preprocess", "full", "--size", "256", "--still", "--batch_size", "8"]
t = time.time()
run(args, cwd=WORK)
videos = sorted(glob.glob(os.path.join(result_dir, "*.mp4")), key=os.path.getmtime)
if not videos:
    raise SystemExit("SadTalker produced no video")
shutil.copyfile(videos[-1], os.path.join(OUT, "talking.mp4"))
log(f"talking face done in {time.time() - t:.0f} s (total {time.time() - T0:.0f} s)")
