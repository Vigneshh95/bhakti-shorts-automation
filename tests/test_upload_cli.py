from pathlib import Path

from shorts.__main__ import resolve_episode
from shorts.config import ROOT
from shorts.upload import build_metadata


def test_upload_metadata_uses_the_pipelines_title_file(tmp_path):
    video = tmp_path / "muruganShorts_2026-01-01.mp4"
    video.write_bytes(b"")
    video.with_suffix(".txt").write_text("பெண்மையைப் போற்று\n", encoding="utf-8")
    _, _, title, tags, description = build_metadata(video)  # no network: metadata only
    assert "பெண்மையைப் போற்று" in title
    assert len(title) <= 100
    assert "#Shorts" in description


def test_episode_can_be_given_by_name_from_any_folder(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # somewhere unrelated, as when make_short.bat is started elsewhere
    assert resolve_episode(Path("sample-2026-03-08")) == ROOT / "episodes" / "sample-2026-03-08"
    assert resolve_episode(Path("episodes/sample-2026-03-08")) == ROOT / "episodes" / "sample-2026-03-08"


def test_uploader_metadata_has_no_filler_typos_or_off_topic_tags(tmp_path):
    import re
    video = tmp_path / "v.mp4"
    video.write_bytes(b"")
    video.with_suffix(".txt").write_text("தாயின் ஆசியே உனது முதல் வெற்றி\n", encoding="utf-8")
    for _ in range(30):  # titles/tags are random; sample many
        _, _, title, tags, description = build_metadata(video)
        assert not re.search(r"#\d|அருள் \d|MuruganTag|முருகன்\d", title + " ".join(tags))
        assert not {"தீபாவளி", "திருப்பதி", "கிளி", "அடை", "வீதி"} & set(tags)
        assert "ஜெய் முருகன்" in description and "ஜெை" not in description
        assert "Sache" not in title


def test_title_templates_do_not_grow_on_every_use():
    from shorts.upload import _uploader_module
    up = _uploader_module()
    before = len(up.MetadataGenerator.TITLE_TEMPLATES)
    cfg = up.Config(ROOT / "config.ini")
    up.MetadataGenerator(cfg)
    up.MetadataGenerator(cfg)
    assert len(up.MetadataGenerator.TITLE_TEMPLATES) == before
