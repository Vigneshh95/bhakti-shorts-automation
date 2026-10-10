"""The Ramana series: one passage of the book a day, never twice, the chapters in turn."""
from datetime import date

from autopilot import planner
from autopilot import script as S
from autopilot.settings import load_settings
from autopilot.sources import passages as P


def _store(tmp_path):
    store = P.Store(tmp_path / "ramana")
    store.save([P.Passage(f"b:{g:03d}:{i:02d}", f"b:{g:03d}", "Book (Author)", "தலைப்பு" if i == 1 else "", "https://x/y",
                          f"பகுதி {g} {i} " + "அமைதி " * 50) for g in (1, 2, 3) for i in (1, 2)])
    return store


def test_passages_are_never_repeated_and_chapters_take_turns(tmp_path):
    store = _store(tmp_path)
    s = load_settings(series="ramana")
    s["paths"]["source"] = store.folder
    history = planner.History(tmp_path / "history.json")
    seen, groups = [], []
    for k in range(6):
        day = date(2026, 10, 11 + k)
        plan = planner.plan_day(day, s, history)
        assert plan.source["id"] not in seen and plan.source["text"]
        seen.append(plan.source["id"])
        groups.append(plan.source["id"].rsplit(":", 1)[0])
        history.add({"date": day.isoformat(), "source_id": plan.source["id"], "title": "t", "theme": plan.theme})
    assert len(set(seen)) == 6
    assert all(a != b for a, b in zip(groups[:3], groups[1:3]))   # neighbouring days: different chapters
    try:
        planner.plan_day(date(2026, 10, 20), s, history)
    except RuntimeError as e:
        assert "add another book" in str(e)
    else:
        raise AssertionError("an empty book must stop the run, not repeat a passage")


def test_split_keeps_whole_paragraphs_and_joins_a_short_tail():
    paras = ["அ" * 900, "ஆ" * 900, "இ" * 900, "ஈ" * 200]
    parts = P.split(paras, low=1400, high=2600)
    assert [len(p.replace("\n", "")) for p in parts] == [1800, 1100]


def test_series_settings_prompt_and_title_rule():
    s = load_settings(series="ramana")
    assert s["look"]["talking"] is False and s["video"]["voice"]["engine"] == "indicf5"
    system, user = S.build_prompt(planner.Plan(date(2026, 10, 11), "x", source={
        "id": "b:1", "credit": "c", "url": "u", "title": "t", "text": "ரமணர் அமைதி"}), s, [], [("a.jpg", "portrait")])
    assert "takeaway" in system and "ரமணர் அமைதி" in user and "{" not in system
    lines = ["மனம் அடங்க வழி என்ன என்று ஒருவர் கேட்டார்."] * 5 + ["இன்று ஒரு நிமிடம் அமைதியாக இருங்கள்."]
    good = {"image_id": "a.jpg", "lines": lines, "keywords": ["அமைதியாக"], "hook_title": "மனம் அடங்க",
            "youtube_title": "மனம் அடங்க என்ன வழி? | ரமணர் சொன்ன பதில்", "youtube_description": "d",
            "hashtags": ["#ரமணமகரிஷி", "#RamanaMaharshi", "#Arunachala"], "tags": ["ramana maharshi"] * 10}
    assert S.validate(good, s, ["a.jpg"]) == []
    bad = dict(good, youtube_title="ரமண மகரிஷி அருள்வாக்கு | Peace")
    assert any("fixed phrase" in e for e in S.validate(bad, s, ["a.jpg"]))
