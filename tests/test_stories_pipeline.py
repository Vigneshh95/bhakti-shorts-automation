"""The story pipeline's decisions: release slots, topics in turn, each series' own channel,
and a thumbnail design that is checked before it is drawn."""
import json
from datetime import datetime

from stories import __main__ as M
from stories import publish as P
from stories import thumbnail as T
from stories import writer


def test_release_slots_are_twice_a_week_and_never_shared():
    cfg = writer.load_settings()["youtube"]["adults"]
    now = datetime(2026, 10, 11, 9, 0, tzinfo=P.IST)                      # a Sunday
    first = P.next_slot(cfg, [], now)
    assert first.isoformat() == "2026-10-14T19:00:00+05:30"              # Wednesday 7 pm
    second = P.next_slot(cfg, [first.isoformat()], now)
    assert second.isoformat() == "2026-10-17T19:00:00+05:30"             # Saturday 7 pm
    late = datetime(2026, 10, 14, 17, 30, tzinfo=P.IST)                   # under 3 hours before the slot: too late for it
    assert P.next_slot(cfg, [], late).isoformat() == "2026-10-17T19:00:00+05:30"


def test_topics_are_told_in_turn_and_start_again_with_the_oldest():
    settings = {"topics": {"adults": ["a", "b", "c"]}}
    rec = lambda t: {"script": {"topic": t}}  # noqa: E731
    assert M._next_topic(settings, "adults", []) == "a"
    assert M._next_topic(settings, "adults", [rec("a"), rec("b")]) == "c"
    assert M._next_topic(settings, "adults", [rec("a"), rec("b"), rec("c"), rec("a")]) == "b"


def test_kids_stories_have_their_own_channel_and_wait_for_its_sign_in(tmp_path, monkeypatch):
    settings = writer.load_settings()
    main, kids = P.channel("adults", settings["youtube"]["adults"]), P.channel("kids", settings["youtube"]["kids"])
    assert kids["token_file"].name == "kids_token.json" and main["token_file"].name != "kids_token.json"
    assert settings["youtube"]["kids"]["made_for_kids"] is True and settings["youtube"]["adults"]["made_for_kids"] is False
    monkeypatch.setenv("YT_TOKEN_FILE_KIDS", str(tmp_path / "missing_token.json"))
    folder = tmp_path / "kids-2026-10-12"
    folder.mkdir()
    (folder / "script.json").write_text(json.dumps({"series": "kids"}), encoding="utf-8")
    assert P.publish(folder, settings, interactive=False) is None       # made, kept, uploaded once someone signs in
    assert not (folder / "published.json").exists()


def test_thumbnail_design_is_checked_and_its_boxes_made_usable():
    script = {"scenes": [{"characters": ["person"]}, {"characters": ["murugan", "peacock"]}]}
    good = {"story_scene": 1, "story_box": [0.2, 0.1, 0.8, 0.7], "murugan_scene": 2, "murugan_box": [0.3, 0.0, 0.7, 0.8],
            "line1": "ஒரே வார்த்தை…", "line2": "வீடே மௌனம்!", "question": "முருகன் கேட்ட அந்த ஒரு கேள்வி என்ன?"}
    assert T.check(good, script) == []
    assert any("WITHOUT Murugan" in e for e in T.check(dict(good, story_scene=2), script))
    assert any("with baby Murugan" in e for e in T.check(dict(good, murugan_scene=1), script))
    assert any("Tamil" in e for e in T.check(dict(good, line1="One word"), script))
    assert any("at most" in e for e in T.check(dict(good, line2="மிக மிக நீளமான ஒரு வரி இது"), script))
    left, top, right, bottom = T._box([0.9, 0.9, 0.95, 0.95], 0.4, 0.5)    # a tiny box in a corner
    assert right - left >= 0.4 - 1e-9 and bottom - top >= 0.5 - 1e-9 and right <= 1 and bottom <= 1
