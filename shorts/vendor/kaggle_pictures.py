"""Runs ON KAGGLE (free GPU), pushed there by autopilot/pictures.py.

Paints new devotional pictures of child Lord Murugan with Z-Image-Turbo (open model, Apache-2.0
licence: pictures may be used commercially; SDXL 1.0 as a backup). Neither needs a sign-in. The prompts are embedded below (JOBS) by
autopilot/pictures.py. Output in /kaggle/working: pictures.zip (PNG files) and run_log.txt.
"""
import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
import subprocess
import sys
import time
import zipfile

JOBS = []  # filled in by autopilot/pictures.py: [{"name": "...", "prompt": "...", "seed": 1}, ...]
WIDTH, HEIGHT = 816, 1456  # 9:16 like a Short, multiples of 16

T0 = time.time()
OUT = "/kaggle/working"
LOG = open(os.path.join(OUT, "run_log.txt"), "w")


def log(*parts):
    line = f"[{time.time() - T0:6.1f}s] " + " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


import socket  # noqa: E402

try:
    socket.gethostbyname("huggingface.co")
except OSError:
    raise SystemExit("NO INTERNET on Kaggle: verify your phone number at kaggle.com/settings")

res = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.36", "transformers>=4.51",
                      "accelerate", "bitsandbytes>=0.45", "sentencepiece", "protobuf"], capture_output=True, text=True)
if res.returncode != 0:
    log(res.stderr[-2000:])
    raise SystemExit("pip install failed")
# torchao is an optional extra that newer diffusers imports if present; the image's copy is too old
# for it ("cannot import name 'FqnToConfig'", 2026-10-06). We quantise with bitsandbytes, not torchao.
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-q", "-y", "torchao"], capture_output=True, text=True)
vers = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True).stdout
log("versions:", ", ".join(l for l in vers.splitlines() if l.split("==")[0].lower() in
                            ("diffusers", "transformers", "accelerate", "bitsandbytes", "torch")))
log("packages ready")

import numpy as np  # noqa: E402
import torch  # noqa: E402

log("GPU:", torch.cuda.get_device_name(0))


def load_z_image(dtype):
    """Z-Image-Turbo (Tongyi-MAI, Apache-2.0, no sign-in needed): 8 steps a picture. Loaded 4-bit
    (NF4): at full size its 6B painter alone fills the free T4's 15 GB. float16 first: the T4 has
    no fast bfloat16 (measured 343 s a picture in bfloat16)."""
    from diffusers import PipelineQuantizationConfig, ZImagePipeline

    quant = PipelineQuantizationConfig(
        quant_backend="bitsandbytes_4bit",
        quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": dtype},
        components_to_quantize=["transformer", "text_encoder"])
    pipe = ZImagePipeline.from_pretrained("Tongyi-MAI/Z-Image-Turbo", torch_dtype=dtype,
                                          quantization_config=quant).to("cuda")
    pipe.vae.to(torch.float32)  # the picture decoder overflows in float16; float32 + tiles is safe and small
    pipe.vae.enable_tiling()
    return f"Z-Image-Turbo {str(dtype).split('.')[-1]}", lambda prompt, g: pipe(
        prompt, width=WIDTH, height=HEIGHT, num_inference_steps=9, guidance_scale=0.0, generator=g).images[0]


def load_sdxl():
    """Backup: Stable Diffusion XL 1.0 (Open RAIL++-M, commercial use allowed, no sign-in)."""
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline

    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
    pipe = StableDiffusionXLPipeline.from_pretrained("stabilityai/stable-diffusion-xl-base-1.0", vae=vae,
                                                     torch_dtype=torch.float16, variant="fp16").to("cuda")
    pipe.vae.enable_tiling()
    negative = "text, letters, watermark, deformed face, extra fingers, extra limbs, blurry, ugly, scary"
    return "SDXL", lambda prompt, g: pipe(prompt, negative_prompt=negative, width=832, height=1472,
                                           num_inference_steps=30, guidance_scale=6.0, generator=g).images[0]


def looks_ok(image):
    a = np.asarray(image, dtype=np.float32)
    return a.std() > 8 and 10 < a.mean() < 245  # not blank / black (half-precision overflow)


# Try each model on the first picture; the first that paints a real picture does them all.
folder = "/tmp/pictures"
os.makedirs(folder, exist_ok=True)
loaders = [lambda: load_z_image(torch.float16), lambda: load_z_image(torch.bfloat16), load_sdxl]
model = paint = None
first = JOBS[0]
for loader in loaders:
    try:
        name, fn = loader()
        t = time.time()
        image = fn(first["prompt"], torch.Generator("cpu").manual_seed(first["seed"]))
        if not looks_ok(image):
            raise RuntimeError("the picture came out blank")
        image.save(os.path.join(folder, first["name"] + ".png"))
        log(f"1/{len(JOBS)} {first['name']} ({time.time() - t:.0f} s)")
        model, paint = name, fn
    except Exception as e:  # noqa: BLE001
        log(f"a model failed: {str(e)[:300]}")
    if paint is not None:
        break
    # outside the except block, so the error no longer holds the failed model: free it for the next one
    import gc

    name = fn = image = None
    gc.collect()
    torch.cuda.empty_cache()
if paint is None:
    raise SystemExit("no picture model could be loaded")
log("model:", model)

for i, job in enumerate(JOBS[1:], 2):
    t = time.time()
    try:
        image = paint(job["prompt"], torch.Generator("cpu").manual_seed(job["seed"]))
    except Exception as e:  # noqa: BLE001 -- one bad picture shouldn't lose the rest
        log(f"{job['name']}: failed ({str(e)[:200]})")
        continue
    if not looks_ok(image):
        log(f"{job['name']}: came out blank, skipped")
        continue
    image.save(os.path.join(folder, job["name"] + ".png"))
    log(f"{i}/{len(JOBS)} {job['name']} ({time.time() - t:.0f} s)")

with zipfile.ZipFile(os.path.join(OUT, "pictures.zip"), "w", zipfile.ZIP_STORED) as z:
    for name in sorted(os.listdir(folder)):
        z.write(os.path.join(folder, name), name)
log(f"done: {len(os.listdir(folder))} pictures in {time.time() - T0:.0f} s")
