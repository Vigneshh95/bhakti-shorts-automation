"""More pictures for the daily choice, painted free on your Kaggle GPU.

  python -m autopilot pictures             paint a new set (about 20) into a review folder
  python -m autopilot pictures --count 10

Z-Image-Turbo (open model, Apache-2.0: the pictures may be used on a monetised channel) runs in
your private Kaggle notebook (shorts/vendor/kaggle_pictures.py). Every picture shows child
Murugan's face clearly and facing the viewer, so the talking face works on it. Pictures where
no face is found are dropped automatically; the rest land in <image_folder>/new_pictures/ for
you to look at. Move the ones you like into the picture folder itself (the autopilot ignores the
review folder), and they'll be described and offered to the writer from the next run."""
from __future__ import annotations

import json
import random
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from shorts.cache import Cache
from shorts.config import ROOT, load_config
from shorts.log import log
from shorts.stages import kaggle_talk, mouth

RUNNER = ROOT / "shorts" / "vendor" / "kaggle_pictures.py"
KERNEL_SLUG = "murugan-pictures"
REVIEW_FOLDER = "new_pictures"

STYLE = ("A beautiful devotional painting of adorable toddler Lord Murugan, the Tamil Hindu god, as a divine "
         "little child: chubby cheeks, big bright kind eyes, sweet gentle smile, looking straight at the viewer, "
         "his face clearly visible, front-facing and softly lit, ornate golden crown, small sacred ash and "
         "vermilion mark on his forehead, golden jewellery, {scene}. Warm golden divine glow, rich detailed "
         "traditional South Indian devotional art style, luminous colours, soft painterly finish, vertical "
         "portrait composition, the child is the only person in the picture, no text, no letters, no watermark.")

# Each scene suits different messages (courage, devotion, mother's love, hard work, festivals…), so the
# writer has a fitting picture for most themes. Only one person (the child) keeps the face unambiguous.
SCENES = [
    "sitting on a majestic peacock with its tail spread, under a banyan tree at sunrise, a hilltop temple far behind",
    "cradled in his mother's gentle hands (her face out of frame), marigold petals falling, a soft halo behind him",
    "playing happily with a peacock feather beside a lotus pond, pink lotuses and dragonflies",
    "seated calmly on a large pink lotus holding a golden Vel spear, snowy Himalayan peaks and a sacred Om glowing in the sky",
    "standing on the shore at Thiruchendur temple by the sea, gentle waves, orange sunset sky, holding a golden Vel",
    "holding a golden Vel high, a rooster banner fluttering beside him, sunrise over green hills, brave and victorious",
    "surrounded by hundreds of glowing oil lamps for the Karthigai Deepam festival, a big flame on the hill behind",
    "beside a kavadi decorated with peacock feathers and marigold garlands at the Thaipusam festival, joyful colours",
    "under a starry night sky with a bright full moon, fireflies around him, peaceful and serene",
    "holding a big lotus leaf as an umbrella in gentle rain, a peacock sheltering beside him, playful",
    "seated with old palm-leaf manuscripts, a glowing Om symbol above his raised hand, teaching wisdom",
    "holding a small clay oil lamp in both hands, its warm flame lighting his smiling face, dark temple hall behind",
    "walking through green paddy fields in a Tamil village at dawn, coconut palms, holding a small Vel",
    "standing on the top of Palani hill holding a golden staff, clouds below, temple tower beside him",
    "sitting beside a playful baby elephant in a lush forest, both happy, sunbeams through the trees",
    "in a flower garden surrounded by colourful butterflies, jasmine and hibiscus, soft morning light",
    "sitting on a small golden throne in a temple sanctum, jasmine garlands, brass lamps, a peacock at his feet",
    "beside a sparkling waterfall in a green forest, a peacock drinking from the stream, mist and rainbow",
    "gently patting a white cow and her calf in a village, compassion, warm evening light",
    "in front of a colourful temple gopuram at dawn, temple bells, jasmine strings, a peacock beside him",
]


def jobs(count: int, seed: int) -> list[dict]:
    """`count` prompts cycling through the scenes (each scene at least once when count >= scenes)."""
    rng = random.Random(seed)
    order = SCENES[:]
    rng.shuffle(order)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")  # unique per run: never overwrites earlier pictures
    return [{"name": f"baby_murugan_{stamp}_{i + 1:02d}", "prompt": STYLE.format(scene=order[i % len(order)]),
             "seed": rng.randrange(1, 2**31)} for i in range(count)]


def _script(job_list: list[dict]) -> str:
    runner = RUNNER.read_text(encoding="utf-8")
    if "JOBS = []" not in runner:
        raise kaggle_talk.KaggleUnavailable("picture runner template is missing its JOBS marker")
    return runner.replace("JOBS = []", "JOBS = " + json.dumps(job_list), 1)


def paint(folder: Path, count: int = 20, timeout_min: int | None = None) -> list[Path]:
    """Paints `count` pictures on Kaggle, keeps those with a clear face, and puts them in
    <folder>/new_pictures/. Returns the kept pictures."""
    user = kaggle_talk.username()
    work = ROOT / ".cache" / "work" / f"pictures_{datetime.now():%Y%m%d_%H%M%S}"
    kernel = work / "kaggle_kernel"
    kernel.mkdir(parents=True)
    job_list = jobs(count, seed=int(time.time()))
    (kernel / "kaggle_pictures.py").write_text(_script(job_list), encoding="utf-8")
    (kernel / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{KERNEL_SLUG}", "title": KERNEL_SLUG, "code_file": "kaggle_pictures.py",
        "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
        "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": []}),
        encoding="utf-8")
    t0 = time.time()
    minutes = 14 + 5 * count  # measured on the free T4: ~14 min to set up, then ~5 min a picture
    timeout_min = timeout_min or minutes + 60
    log.info("painting %d pictures on your private Kaggle GPU (about %s)…", count,
             f"{minutes} min" if minutes < 90 else f"{minutes / 60:.1f} hours; you can use the laptop meanwhile")
    kaggle_talk._kaggle("kernels", "push", "-p", ".", cwd=kernel, timeout=900)

    ref = f"{user}/{KERNEL_SLUG}"
    time.sleep(30)
    _wait(ref, t0, timeout_min)
    dest = kaggle_talk._fetch_output(ref, work)
    archive = dest / "pictures.zip"
    if not archive.exists():
        raise kaggle_talk.KaggleUnavailable(f"the Kaggle run finished without pictures: {kaggle_talk._tail(dest)}")
    return _keep(archive, work, folder, t0)


def _wait(ref: str, t0: float, timeout_min: int) -> None:
    last_note, failures = 0.0, []
    while True:
        state = kaggle_talk.status(ref, failures)
        if "complete" in state:
            return
        if "error" in state or "cancel" in state:
            dest = kaggle_talk._fetch_output(ref, ROOT / ".cache" / "work")
            raise kaggle_talk.KaggleUnavailable(f"the Kaggle run failed: {kaggle_talk._tail(dest)}")
        if time.time() - t0 > timeout_min * 60:
            raise kaggle_talk.KaggleUnavailable(f"the Kaggle run took longer than {timeout_min} minutes")
        if time.time() - last_note > 300:
            last_note = time.time()
            log.info("  …Kaggle GPU painting (%d min so far)", (time.time() - t0) // 60)
        time.sleep(30)


def _keep(archive: Path, work: Path, folder: Path, t0: float) -> list[Path]:
    """Unpacks the painted pictures and keeps those with a clear face in the review folder."""
    painted = work / "painted"
    with zipfile.ZipFile(archive) as z:
        z.extractall(painted)
    log.info("  %d pictures painted in %.0f min; checking each has a clear face…",
             len(list(painted.glob("*.png"))), (time.time() - t0) / 60)

    cfg = load_config()
    t = cfg["talking"]
    python = Path(t["python"]) if Path(t["python"]).is_absolute() else ROOT / t["python"]
    sadtalker = Path(t["dir"]) if Path(t["dir"]).is_absolute() else ROOT / t["dir"]
    cache = Cache(cfg["paths"]["cache"])
    review = folder / REVIEW_FOLDER
    review.mkdir(parents=True, exist_ok=True)
    kept = []
    for png in sorted(painted.glob("*.png")):
        if mouth.find_landmarks(png, python, sadtalker, cache) is None:
            log.info("  %s: no clear face, dropped", png.name)
            continue
        shutil.copyfile(png, review / png.name)
        kept.append(review / png.name)
    log.info("✅ %d new pictures in %s -- move the ones you like into %s", len(kept), review, folder)
    return kept
