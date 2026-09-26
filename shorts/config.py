"""Loads config.toml, applies the chosen speed/quality preset, then the episode's own
episode.toml overrides. The result is a plain nested dict plus resolved absolute paths."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(episode_dir: Path | None = None, preset: str | None = None, config_path: Path | None = None) -> dict:
    config_path = config_path or ROOT / "config.toml"
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    episode_overrides = {}
    if episode_dir is not None and (episode_dir / "episode.toml").exists():
        with open(episode_dir / "episode.toml", "rb") as f:
            episode_overrides = tomllib.load(f)

    preset = preset or episode_overrides.get("run", {}).get("preset") or cfg["run"]["preset"]
    presets = cfg.pop("presets", {})
    if preset not in presets:
        raise ValueError(f"Unknown preset '{preset}'. Choose one of: {', '.join(presets)}")
    cfg = deep_merge(cfg, presets[preset])
    cfg = deep_merge(cfg, episode_overrides)
    cfg["run"]["preset"] = preset

    style = cfg["voice"]["style"]
    if style not in cfg["voice"]["styles"]:
        raise ValueError(f"Unknown voice style '{style}'. Choose one of: {', '.join(cfg['voice']['styles'])}")

    cfg["paths"] = {k: _resolve(v) for k, v in cfg["paths"].items()}
    return cfg


def _resolve(value: str) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else ROOT / p
