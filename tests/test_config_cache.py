from pathlib import Path

import pytest

from shorts.cache import Cache
from shorts.config import ROOT, load_config


def test_balanced_is_the_default_preset(cfg):
    assert cfg["run"]["preset"] == "balanced"
    assert cfg["video"]["width"] == 1080 and cfg["video"]["height"] == 1920


def test_preset_overrides_nested_settings():
    fast = load_config(preset="fast")
    assert fast["effects"]["bloom"]["enabled"] is False
    assert fast["effects"]["particles"]["count"] == 35
    assert fast["effects"]["particles"]["opacity"] == 0.85  # untouched keys survive the merge


def test_episode_toml_overrides_config(tmp_path):
    (tmp_path / "episode.toml").write_text('[voice]\nstyle = "male"\n[captions]\nsize = 60\n', encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg["voice"]["style"] == "male"
    assert cfg["captions"]["size"] == 60


def test_unknown_preset_is_a_clear_error():
    with pytest.raises(ValueError, match="Unknown preset"):
        load_config(preset="ultra")


def test_paths_resolve_relative_to_the_project(cfg):
    assert cfg["paths"]["ffmpeg"] == ROOT / "tools/ffmpeg/bin/ffmpeg.exe"


def test_cache_key_changes_with_any_input(tmp_path):
    c = Cache(tmp_path)
    assert c.key("tts", "line", "female") == c.key("tts", "line", "female")
    assert c.key("tts", "line", "female") != c.key("tts", "line", "male")
    assert c.key("tts", "line", "female") != c.key("tts", "line2", "female")


def test_cache_key_tracks_file_contents(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"a")
    c = Cache(tmp_path)
    k1 = c.key("bake", f)
    f.write_bytes(b"b")
    assert c.key("bake", f) != k1
