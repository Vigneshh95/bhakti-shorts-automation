"""Talking face on Kaggle's free GPU ([talking] method = "kaggle").

SadTalker on this laptop's CPU takes about an hour per Short; on a free Kaggle GPU the same
animation takes minutes. This stage sends only today's picture + voice (~5 MB) to your private
Kaggle notebook, runs SadTalker there (shorts/vendor/kaggle_sadtalker.py), and downloads the
talking video. Everything on Kaggle is private to your account.

Setup once: run  .venv\\Scripts\\kaggle.exe auth login  and approve in the browser (or put an
API token in %USERPROFILE%\\.kaggle\\access_token). Uses the official `kaggle` command-line tool.
If Kaggle isn't set up, fails, or takes too long, the caller falls back to the laptop."""
from __future__ import annotations

import json
import re
import os
import shutil
import subprocess
import time
from pathlib import Path

from shorts.config import ROOT
from shorts.log import log

KAGGLE = ROOT / ".venv" / "Scripts" / "kaggle.exe"
RUNNER = Path(__file__).resolve().parent.parent / "vendor" / "kaggle_sadtalker.py"
KERNEL_SLUG = "murugan-talking"


class KaggleUnavailable(RuntimeError):
    pass


def _kaggle(*args: str, cwd: Path | None = None, timeout: int = 600) -> str:
    """Runs the kaggle tool. Paths are passed as "." with cwd set, because on Windows the tool
    builds temp-file names from the folder path and breaks on anything else."""
    try:
        res = subprocess.run([str(KAGGLE), "-W", *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, cwd=cwd,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KaggleUnavailable(f"kaggle {' '.join(args[:2])}: {e}") from e
    out = (res.stdout or "") + (res.stderr or "")
    failed = res.returncode != 0
    if args[:2] == ("kernels", "push") and "successfully pushed" not in out.lower():
        failed = True  # the tool can print an HTTP error and still exit 0
    if failed:
        raise KaggleUnavailable(f"kaggle {' '.join(args[:2])} failed: {out.strip().splitlines()[-1] if out.strip() else res.returncode}")
    return out


def status(ref: str, failures: list[float]) -> str:
    """The run's status, lower-case; "" while the laptop's internet blips. Gives up only after
    10 minutes without any answer from Kaggle."""
    try:
        out = _kaggle("kernels", "status", ref, timeout=120).lower()
        failures.clear()
        return out
    except KaggleUnavailable as e:
        failures.append(time.time())
        if time.time() - failures[0] > 600:
            raise
        log.debug("Kaggle status check failed (will retry): %s", e)
        return ""


def username() -> str:
    out = _kaggle("config", "view")
    for line in out.splitlines():
        key, _, value = line.strip().lstrip("-").partition(":")
        if key.strip().lower() == "username" and value.strip() and value.strip().lower() != "none":
            return value.strip()
    raise KaggleUnavailable(r"not signed in to Kaggle -- run: .venv\Scripts\kaggle.exe auth login")


def _face_crop(picture: "np.ndarray", points: "np.ndarray", max_side: int = 512):
    """Square around the face with room for hair and head motion. Returns (crop, (x0, y0, side), scale)."""
    import numpy as np

    H, W = picture.shape[:2]
    (fx0, fy0), (fx1, fy1) = points.min(axis=0), points.max(axis=0)
    fw, fh = fx1 - fx0, fy1 - fy0
    side = int(min(W, H, 2.4 * max(fw, fh)))
    cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2 - 0.12 * fh  # a little above centre: include forehead/hair
    x0 = int(np.clip(cx - side / 2, 0, W - side))
    y0 = int(np.clip(cy - side / 2, 0, H - side))
    crop = picture[y0:y0 + side, x0:x0 + side]
    scale = min(1.0, max_side / side)
    return crop, (x0, y0, side), scale


def _code_zip(sadtalker: Path) -> bytes:
    """The laptop's working SadTalker code (no model weights; ~200 KB). The original frame loop
    is used: the GPU doesn't need the CPU speed-ups."""
    import io
    import zipfile

    skip = {"checkpoints", "gfpgan", "results", ".git", "docs", "examples"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(sadtalker.rglob("*")):
            rel = p.relative_to(sadtalker)
            if p.is_dir() or rel.parts[0] in skip or "__pycache__" in rel.parts or p.suffix in (".orig", ".ipynb"):
                continue
            src = p
            if rel.as_posix() == "src/facerender/modules/make_animation.py" and p.with_name("make_animation.py.orig").exists():
                src = p.with_name("make_animation.py.orig")
            z.write(src, "sadtalker/" + rel.as_posix())
    return buf.getvalue()


def _script_with_inputs(face_jpg: bytes, voice_ogg: bytes, code_zip: bytes) -> str:
    import base64

    inputs = {"face.jpg": base64.b64encode(face_jpg).decode(), "voice.ogg": base64.b64encode(voice_ogg).decode(),
              "sadtalker.zip": base64.b64encode(code_zip).decode()}
    runner = RUNNER.read_text(encoding="utf-8")
    marker = "INPUTS = {}"
    if marker not in runner:
        raise KaggleUnavailable("Kaggle runner template is missing its INPUTS marker")
    script = runner.replace(marker, "INPUTS = " + json.dumps(inputs), 1)
    if len(script) > 900_000:  # Kaggle rejects notebooks around 2 MB; stay well under
        raise KaggleUnavailable(f"inputs too large for a Kaggle notebook ({len(script) // 1024} KB)")
    return script


def animate(picture_png: Path, voice_wav: Path, points, ffmpeg: Path, work: Path, out: Path,
            timeout_min: int = 40) -> Path:
    """Runs SadTalker on Kaggle for the face region and blends the animated face back into the
    full picture. Returns `out` (full-size talking video) or raises KaggleUnavailable."""
    import cv2

    if not KAGGLE.exists():
        raise KaggleUnavailable("the kaggle tool isn't installed (pip install kaggle)")
    user = username()
    t0 = time.time()
    picture = cv2.imread(str(picture_png))
    crop, box, scale = _face_crop(picture, points)
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
    ogg = work / "voice_for_kaggle.ogg"
    subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-i", str(voice_wav), "-ac", "1", "-c:a", "libopus",
                    "-b:a", "32k", str(ogg)], check=True)

    kernel = work / "kaggle_kernel"
    shutil.rmtree(kernel, ignore_errors=True)
    kernel.mkdir(parents=True)
    sadtalker = ROOT / "SadTalker"
    script = _script_with_inputs(jpg.tobytes(), ogg.read_bytes(), _code_zip(sadtalker))
    (kernel / "kaggle_sadtalker.py").write_text(script, encoding="utf-8")
    log.debug("Kaggle notebook size: %d KB", len(script) // 1024)
    (kernel / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "kaggle_sadtalker.py",
        "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
        "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": []}),
        encoding="utf-8")
    log.info("  sending the face and voice to your private Kaggle notebook and starting the free GPU…")
    _kaggle("kernels", "push", "-p", ".", cwd=kernel, timeout=900)

    ref = f"{user}/{KERNEL_SLUG}"
    end = time.time() + timeout_min * 60
    last_note = 0.0
    failures: list[float] = []
    time.sleep(30)
    while True:
        state = status(ref, failures)
        if "complete" in state:
            break
        if "error" in state or "cancel" in state:
            dest = _fetch_output(ref, work)
            raise KaggleUnavailable(f"the Kaggle run failed: {_tail(dest)}")
        if time.time() > end:
            raise KaggleUnavailable(f"the Kaggle run took longer than {timeout_min} minutes")
        if time.time() - last_note > 180:
            last_note = time.time()
            log.info("  …Kaggle GPU working (%d min so far)", (time.time() - t0) // 60)
        time.sleep(20)

    dest = _fetch_output(ref, work)
    face_video = dest / "talking.mp4"
    if not face_video.exists():
        raise KaggleUnavailable(f"the Kaggle run finished but produced no video: {_tail(dest)}")
    log.info("  face animated on Kaggle in %.1f min (%s); blending it into the full picture…",
             (time.time() - t0) / 60, _tail(dest))
    _composite(picture, face_video, box, points, ffmpeg, out)
    return out


def _composite(picture, face_video: Path, box, points, ffmpeg: Path, out: Path) -> None:
    """Pastes each animated face frame back into the full-resolution picture through a soft oval
    mask around the face, so everything outside the face stays pixel-identical to the picture."""
    import cv2
    import numpy as np

    x0, y0, side = box
    H, W = picture.shape[:2]
    (fx0, fy0), (fx1, fy1) = points.min(axis=0), points.max(axis=0)
    fw, fh = fx1 - fx0, fy1 - fy0
    mask = np.zeros((side, side), np.float32)
    centre = (int((fx0 + fx1) / 2 - x0), int((fy0 + fy1) / 2 - y0))
    cv2.ellipse(mask, centre, (int(0.72 * fw), int(0.85 * fh)), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
    sigma = max(3.0, 0.07 * fw)
    mask = cv2.GaussianBlur(mask, (0, 0), sigma)[..., None]
    base = picture.astype(np.float32)
    region = base[y0:y0 + side, x0:x0 + side]

    cap = cv2.VideoCapture(str(face_video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    enc = subprocess.Popen([str(ffmpeg), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "14", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    frame_full = picture.copy()
    try:
        while True:
            ok, face = cap.read()
            if not ok:
                break
            face = cv2.resize(face, (side, side), interpolation=cv2.INTER_CUBIC).astype(np.float32)
            frame_full[y0:y0 + side, x0:x0 + side] = np.clip(region * (1 - mask) + face * mask, 0, 255).astype(np.uint8)
            enc.stdin.write(frame_full.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
        cap.release()
    if enc.returncode != 0 or not out.exists():
        raise KaggleUnavailable("couldn't assemble the full-size talking video")


def _fetch_output(ref: str, work: Path) -> Path:
    dest = work / "kaggle_output"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    try:
        _kaggle("kernels", "output", ref, "-p", ".", "-o", cwd=dest, timeout=900)
    except KaggleUnavailable as e:
        log.debug("couldn't fetch Kaggle output: %s", e)
    return dest


def run_kernel(slug: str, script: str, work: Path, timeout_min: int, doing: str = "working") -> Path:
    """Pushes `script` as the private GPU notebook <you>/<slug>, waits for it, and returns the
    folder its /kaggle/working output was downloaded to. Raises KaggleUnavailable on failure,
    with the notebook's own error message."""
    if not KAGGLE.exists():
        raise KaggleUnavailable("the kaggle tool isn't installed (pip install kaggle)")
    user = username()
    kernel = work / f"kaggle_{slug}"
    shutil.rmtree(kernel, ignore_errors=True)
    kernel.mkdir(parents=True)
    (kernel / "script.py").write_text(script, encoding="utf-8")
    (kernel / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{slug}", "title": slug, "code_file": "script.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}), encoding="utf-8")
    t0 = time.time()
    _kaggle("kernels", "push", "-p", ".", cwd=kernel, timeout=900)
    ref, failures, last_note = f"{user}/{slug}", [], time.time()
    time.sleep(30)
    while True:
        state = status(ref, failures)
        if "complete" in state:
            return _fetch_output(ref, work / f"kaggle_{slug}_out")
        if "error" in state or "cancel" in state:
            raise KaggleUnavailable(f"the Kaggle run failed: {_tail(_fetch_output(ref, work / f'kaggle_{slug}_out'))}")
        if time.time() - t0 > timeout_min * 60:
            raise KaggleUnavailable(f"the Kaggle run took longer than {timeout_min} minutes")
        if time.time() - last_note > 180:
            last_note = time.time()
            log.info("  …Kaggle GPU %s (%d min so far)", doing, (time.time() - t0) // 60)
        time.sleep(20)


def _tail(folder: Path) -> str:
    """The notebook's own error (SystemExit / exception line) if it has one, else the last
    line of the run's own log, else of Kaggle's notebook log."""
    for kl in folder.glob("*.log"):
        try:
            events = json.loads(kl.read_text(encoding="utf-8", errors="replace"))
            text = "".join(e.get("data", "") for e in events if e.get("stream_name") == "stderr")
            errors = [l for l in text.splitlines() if re.match(r"^(SystemExit|\w+(Error|Exception))\b", l.strip())]
            if errors:
                return errors[-1].strip()[:300]
        except (ValueError, AttributeError):
            continue
    ours = folder / "run_log.txt"
    if ours.exists():
        lines = [l for l in ours.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        if lines:
            return lines[-1][:300]
    for kl in folder.glob("*.log"):
        try:
            events = json.loads(kl.read_text(encoding="utf-8", errors="replace"))
            text = "".join(e.get("data", "") for e in events if e.get("stream_name") in ("stdout", "stderr"))
            lines = [l for l in text.splitlines() if l.strip() and "Warning" not in l]
            if lines:
                return lines[-1][:300]
        except (ValueError, AttributeError):
            continue
    return "(no log)"
