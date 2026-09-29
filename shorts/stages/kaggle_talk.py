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
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from shorts.config import ROOT
from shorts.log import log

KAGGLE = ROOT / ".venv" / "Scripts" / "kaggle.exe"
RUNNER = Path(__file__).resolve().parent.parent / "vendor" / "kaggle_sadtalker.py"
CODE_SLUG, INPUT_SLUG, KERNEL_SLUG = "murugan-sadtalker-code", "murugan-talking-input", "murugan-talking"


class KaggleUnavailable(RuntimeError):
    pass


def _kaggle(*args: str, timeout: int = 600) -> str:
    try:
        res = subprocess.run([str(KAGGLE), "-W", *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KaggleUnavailable(f"kaggle {' '.join(args[:2])}: {e}") from e
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip()
        raise KaggleUnavailable(f"kaggle {' '.join(args[:2])} failed: {msg.splitlines()[-1] if msg else res.returncode}")
    return res.stdout


def username() -> str:
    out = _kaggle("config", "view")
    for line in out.splitlines():
        key, _, value = line.strip().lstrip("-").partition(":")
        if key.strip().lower() == "username" and value.strip() and value.strip().lower() != "none":
            return value.strip()
    raise KaggleUnavailable("not signed in to Kaggle -- run: .venv\\Scripts\\kaggle.exe auth login")


def _dataset_ready(ref: str, wait_s: int = 300) -> bool:
    end = time.time() + wait_s
    while time.time() < end:
        try:
            status = _kaggle("datasets", "status", ref).strip().lower()
        except KaggleUnavailable:
            status = ""
        if "ready" in status:
            return True
        time.sleep(10)
    return False


def _publish_dataset(folder: Path, ref: str, title: str, note: str) -> None:
    (folder / "dataset-metadata.json").write_text(json.dumps(
        {"title": title, "id": ref, "licenses": [{"name": "other"}]}), encoding="utf-8")
    try:
        _kaggle("datasets", "status", ref)
        exists = True
    except KaggleUnavailable:
        exists = False
    if exists:
        _kaggle("datasets", "version", "-p", str(folder), "-m", note, "-q", timeout=900)
    else:
        _kaggle("datasets", "create", "-p", str(folder), "-q", timeout=900)  # private by default
    if not _dataset_ready(ref):
        raise KaggleUnavailable(f"Kaggle dataset {ref} didn't become ready")


def _ensure_code(user: str, sadtalker: Path, work: Path) -> None:
    """Uploads SadTalker's code (no model weights, a few MB) once, and again only if it changes.
    The original frame loop is used there: the GPU doesn't need the CPU speed-ups."""
    stamp = ROOT / ".cache" / "kaggle_code.stamp"
    folder = work / "kaggle_code"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    zpath = folder / "SadTalker.zip"
    skip = {"checkpoints", "gfpgan", "results", "__pycache__", ".git", "docs", "examples"}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(sadtalker.rglob("*")):
            rel = p.relative_to(sadtalker)
            if p.is_dir() or rel.parts[0] in skip or "__pycache__" in rel.parts or p.suffix in (".orig",):
                continue
            src = p
            if rel.as_posix() == "src/facerender/modules/make_animation.py" and p.with_name("make_animation.py.orig").exists():
                src = p.with_name("make_animation.py.orig")
            z.write(src, "sadtalker/" + rel.as_posix())
    digest = str(zpath.stat().st_size) + ":" + str(sum(1 for _ in zipfile.ZipFile(zpath).namelist()))
    ref = f"{user}/{CODE_SLUG}"
    if stamp.exists() and stamp.read_text() == f"{ref}|{digest}":
        return
    log.info("  uploading SadTalker's code to your private Kaggle storage (once)…")
    _publish_dataset(folder, ref, "Murugan SadTalker code", "code update")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{ref}|{digest}")


def animate(picture_png: Path, voice_wav: Path, sadtalker: Path, work: Path, out: Path, timeout_min: int = 40) -> Path:
    """Runs SadTalker on Kaggle; returns `out` (the talking video) or raises KaggleUnavailable."""
    if not KAGGLE.exists():
        raise KaggleUnavailable("the kaggle tool isn't installed (pip install kaggle)")
    user = username()
    t0 = time.time()
    _ensure_code(user, sadtalker, work)

    inputs = work / "kaggle_input"
    shutil.rmtree(inputs, ignore_errors=True)
    inputs.mkdir(parents=True)
    shutil.copyfile(picture_png, inputs / "talking_source.png")
    shutil.copyfile(voice_wav, inputs / "voice_16k.wav")
    log.info("  sending today's picture and voice to Kaggle…")
    _publish_dataset(inputs, f"{user}/{INPUT_SLUG}", "Murugan talking input", time.strftime("%Y-%m-%d %H:%M"))

    kernel = work / "kaggle_kernel"
    shutil.rmtree(kernel, ignore_errors=True)
    kernel.mkdir(parents=True)
    shutil.copyfile(RUNNER, kernel / "kaggle_sadtalker.py")
    (kernel / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "kaggle_sadtalker.py",
        "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
        "enable_internet": True, "dataset_sources": [f"{user}/{CODE_SLUG}", f"{user}/{INPUT_SLUG}"],
        "competition_sources": [], "kernel_sources": []}), encoding="utf-8")
    log.info("  starting the free GPU on Kaggle…")
    _kaggle("kernels", "push", "-p", str(kernel))

    ref = f"{user}/{KERNEL_SLUG}"
    end = time.time() + timeout_min * 60
    last_note = 0.0
    time.sleep(20)
    while True:
        status = _kaggle("kernels", "status", ref).lower()
        if "complete" in status:
            break
        if "error" in status or "cancel" in status:
            _fetch_output(ref, work)
            tail = _tail(work / "kaggle_output" / "run_log.txt")
            raise KaggleUnavailable(f"the Kaggle run failed: {tail}")
        if time.time() > end:
            raise KaggleUnavailable(f"the Kaggle run took longer than {timeout_min} minutes")
        if time.time() - last_note > 180:
            last_note = time.time()
            log.info("  …Kaggle GPU working (%d min so far)", (time.time() - t0) // 60)
        time.sleep(20)

    got = _fetch_output(ref, work) / "talking.mp4"
    if not got.exists():
        raise KaggleUnavailable("the Kaggle run finished but produced no video")
    shutil.copyfile(got, out)
    log.info("  talking face from Kaggle in %.1f min (%s)", (time.time() - t0) / 60,
             _tail(work / "kaggle_output" / "run_log.txt"))
    return out


def _fetch_output(ref: str, work: Path) -> Path:
    dest = work / "kaggle_output"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    try:
        _kaggle("kernels", "output", ref, "-p", str(dest), "-o", timeout=900)
    except KaggleUnavailable as e:
        log.debug("couldn't fetch Kaggle output: %s", e)
    return dest


def _tail(path: Path) -> str:
    if not path.exists():
        return "(no log)"
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    return lines[-1][:300] if lines else "(empty log)"
