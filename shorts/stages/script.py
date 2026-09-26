"""Script stage: reads an episode folder.

episodes/<name>/
  lines.txt        one Tamil sentence per line (blank lines and lines starting with # ignored)
  images/          one or more .png/.jpg/.jpeg/.webp (used in file-name order)
  episode.toml     optional: [episode] title = "..."  plus any config.toml override
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class Episode:
    name: str
    folder: Path
    lines: list[str]
    images: list[Path]
    title: str


def load_episode(folder: Path) -> Episode:
    if not folder.is_dir():
        raise FileNotFoundError(f"Episode folder not found: {folder}")
    lines_file = folder / "lines.txt"
    if not lines_file.exists():
        raise FileNotFoundError(f"Missing {lines_file} (one Tamil sentence per line)")
    lines = [l.strip() for l in lines_file.read_text(encoding="utf-8-sig").splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    if not lines:
        raise ValueError(f"{lines_file} has no lines")

    img_dir = folder / "images"
    images = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS) if img_dir.is_dir() else []
    if not images:
        raise FileNotFoundError(f"No images in {img_dir} (add at least one .png/.jpg)")

    title = ""
    if (folder / "episode.toml").exists():
        with open(folder / "episode.toml", "rb") as f:
            title = tomllib.load(f).get("episode", {}).get("title", "")
    return Episode(folder.name, folder, lines, images, title)
