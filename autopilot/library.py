"""Your image folder, understood once. Each new picture is described by Gemini's free vision
model (several per request) and cached in <folder>/.library.json, keyed by file content, so
renaming or re-adding a picture never costs another look. Unreadable or unsuitable pictures
are kept out of the daily choice."""
from __future__ import annotations

import hashlib
import io
import json
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from autopilot.http import ProviderError
from shorts.log import log

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
INDEX_NAME = ".library.json"
BATCH = 6          # pictures per vision request (keeps within the free tier's daily request limit)
MIN_SIDE = 700     # smaller pictures look soft at 1080x1920

DESCRIBE_SYSTEM = """You catalogue devotional images of Lord Murugan for a Tamil YouTube Shorts channel.
For every image, identified by its label, return: a one-sentence description (who/what is shown,
setting, colours); the mood; 3-6 themes it would suit (e.g. courage, devotion, family, mother's
blessing, hard work, peace, festival, victory, children, nature); any visible text painted in the
image and what it means (empty if none); and suitable=false only if it is blurry, low quality,
cut off, has a large watermark/logo, or is not a respectful devotional image."""

DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {"images": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string"}, "description": {"type": "string"}, "mood": {"type": "string"},
            "themes": {"type": "array", "items": {"type": "string"}},
            "visible_text": {"type": "string"}, "suitable": {"type": "boolean"},
        },
        "required": ["label", "description", "mood", "themes", "visible_text", "suitable"],
        "additionalProperties": False}}},
    "required": ["images"],
    "additionalProperties": False,
}


@dataclass
class Picture:
    path: Path
    digest: str
    info: dict | None  # None = not described (yet)

    @property
    def id(self) -> str:
        return self.path.name

    def summary(self) -> str:
        if not self.info:
            return "(no description yet)"
        text = f"; painted text: {self.info['visible_text']}" if self.info.get("visible_text") else ""
        return f"{self.info['description']} Mood: {self.info['mood']}. Suits: {', '.join(self.info['themes'])}{text}"


def _digest(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def _thumb(path: Path) -> bytes | None:
    try:
        with Image.open(path) as im:
            if min(im.size) < MIN_SIDE:
                return None
            im = im.convert("RGB")
            im.thumbnail((512, 512))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
            return buf.getvalue()
    except OSError:
        return None


def load(folder: Path, describe=None) -> list[Picture]:
    """All usable pictures in the folder. `describe(system, user, schema, images)` is called for
    pictures not yet in the index; if it fails, those pictures are still usable, just undescribed."""
    folder.mkdir(parents=True, exist_ok=True)
    index_path = folder / INDEX_NAME
    index: dict = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}

    pictures, todo = [], []
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS):
        digest = _digest(path)
        entry = index.get(digest)
        if entry and entry.get("unusable"):
            continue
        pic = Picture(path, digest, entry)
        pictures.append(pic)
        if entry is None:
            todo.append(pic)

    if todo and describe:
        log.info("  describing %d new picture(s) in %s…", len(todo), folder.name)
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            thumbs = [(p.id, _thumb(p.path)) for p in batch]
            for p, (_, jpeg) in zip(batch, thumbs):
                if jpeg is None:  # too small or unreadable: never offered
                    index[p.digest] = {"unusable": True, "name": p.id}
                    log.warning("  %s is too small or unreadable; skipping it", p.id)
            thumbs = [(label, jpeg) for label, jpeg in thumbs if jpeg]
            if not thumbs:
                continue
            try:
                result = describe(DESCRIBE_SYSTEM, "Describe each image above.", DESCRIBE_SCHEMA, thumbs)
            except (ProviderError, ValueError, KeyError) as e:
                log.warning("  couldn't describe pictures right now (%s); they'll be described next time",
                            str(e).splitlines()[0][:120])
                break
            by_label = {r["label"]: r for r in result.get("images", [])}
            for p in batch:
                r = by_label.get(p.id)
                if r:
                    info = {k: r[k] for k in ("description", "mood", "themes", "visible_text", "suitable")}
                    index[p.digest] = {**info, "name": p.id} if r["suitable"] else {"unusable": True, "name": p.id,
                                                                                     "description": r["description"]}
                    p.info = info if r["suitable"] else None
                    if not r["suitable"]:
                        log.warning("  %s judged unsuitable (%s); it won't be used", p.id, r["description"][:80])
        tmp = index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(index_path)

    return [p for p in pictures if not (index.get(p.digest) or {}).get("unusable")]


def candidates(pictures: list[Picture], usage: dict[str, list[str]], yesterday: str | None,
               limit: int, seed: int) -> list[Picture]:
    """Least-used pictures first (never-used before used), never yesterday's, a few random
    extras for variety. usage: digest -> list of dates it was used."""
    pool = [p for p in pictures if p.digest != yesterday] or pictures
    rng = random.Random(seed)
    rng.shuffle(pool)  # random order among equally-used pictures
    pool.sort(key=lambda p: (len(usage.get(p.digest, [])), max(usage.get(p.digest, [""]))))
    return pool[:limit]
