"""Gets the day's background image: from the configured AI provider, with an optional fallback
(default: the next unused picture in assets/auto_images) so one failed image call doesn't
cost the day's Short."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from autopilot.http import ProviderError
from shorts.log import log

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MIN_SIDE = 700  # smaller than this would look soft at 1080x1920


def _ai_image(provider: str, settings: dict, prompt: str) -> bytes:
    if provider == "gemini":
        from autopilot.providers import gemini as p
    elif provider == "openai":
        from autopilot.providers import openai as p
    else:
        raise ValueError(f"Unknown image provider '{provider}' (use gemini, openai or folder)")
    data, _ = p.generate_image(settings["models"][f"{provider}_image"], prompt)
    return data


def _from_folder(settings: dict, used: set[str]) -> Path:
    folder = settings["paths"]["image_folder"]
    candidates = sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_EXTS) if folder.exists() else []
    fresh = [p for p in candidates if p.name not in used]
    if not candidates:
        raise ProviderError(f"No images in {folder} for the folder image source")
    if not fresh:
        log.warning("  every image in %s has been used; reusing the oldest", folder)
        fresh = candidates
    return fresh[0]


def get_image(settings: dict, prompt: str, out_dir: Path, used_folder_images: set[str]) -> tuple[Path, str]:
    """Returns (saved image path, source description)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    order = [settings["providers"]["image"]]
    fallback = settings["providers"].get("fallback_image")
    if fallback and fallback not in order:
        order.append(fallback)

    last_error = None
    for source in order:
        try:
            if source == "folder":
                src = _from_folder(settings, used_folder_images)
                img = Image.open(src)
                label = f"folder:{src.name}"
            else:
                log.info("  generating image with %s (%s)", source, settings["models"][f"{source}_image"])
                img = Image.open(io.BytesIO(_ai_image(source, settings, prompt)))
                label = f"{source}:{settings['models'][f'{source}_image']}"
            img = img.convert("RGB")
            if min(img.size) < MIN_SIDE:
                raise ProviderError(f"image from {label} is only {img.size[0]}x{img.size[1]}")
            path = out_dir / "01.png"
            img.save(path)
            return path, label
        except (ProviderError, OSError, ValueError) as e:
            last_error = e
            log.warning("  image source '%s' failed: %s", source, e)
    raise RuntimeError(f"Could not get an image from any source ({', '.join(order)}): {last_error}")
