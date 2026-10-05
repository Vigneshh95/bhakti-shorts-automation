"""The Sri Mahaperiyava series: chapter source, grounded planning, series settings and look,
the cloned-voice stage's caching, and the upload description."""
import json
import tomllib
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import soundfile as sf

from autopilot import planner, youtube
from autopilot import script as S
from autopilot.run import _episode_toml, _toml
from autopilot.settings import load_settings
from autopilot.sources import deivathin_kural as dk
from shorts.cache import Cache
from shorts.config import deep_merge, load_config
from shorts.stages import audio, tts_indicf5

INDEX = """<a href="/tamil/part1index.htm">முதல் பாகம்</a> <a href="#">தெய்வத்தின் குரல்</a>
<a href="part1kural1.htm">விநாயகர்</a> <a href="part1kural2.htm"><b>அம்மா</b></a>
<a href="part2index.htm">பாகம் 2</a> <a href="part1kural1.htm">விநாயகர்</a> <a href="x.htm">Next</a>"""
PAGE = """<html><nav>மெனு மெனு மெனு</nav><p>அம்மா : தெய்வத்தின் குரல் (முதல் பகுதி) அம்மா அம்மா அம்மா அம்மா அம்மா</p>
<p>தாயன்பைப்போலக் கலப்படமே இல்லாத பூரணமான அன்பை இந்த லோகத்தில் வேறெங்குமே காண முடியவில்லை என்று சொல்கிறோம்.</p>
<p>short</p><p>Quick jump</p><p>விநாயகர் விநாயகர் விநாயகர் விநாயகர் விநாயகர் விநாயகர் விநாயகர் விநாயகர் விநாயகர்</p></html>"""


def test_chapter_links_and_text():
    assert dk.chapter_links(INDEX) == [("part1kural1.htm", "விநாயகர்"), ("part1kural2.htm", "அம்மா")]
    text = dk.chapter_text(PAGE)
    assert text.startswith("தாயன்பைப்போல") and "Quick" not in text and "(முதல் பகுதி)" not in text
    assert "விநாயகர் விநாயகர்" not in text  # the chapter list after "Quick jump" is not part of the talk


def _store(tmp_path: Path) -> dk.Store:
    store = dk.Store(tmp_path / "dk")
    store.folder.mkdir()
    rows = [{"part": p, "index": i, "title": f"t{p}{i}", "url": f"{dk.BASE}p{p}c{i}.htm", "text": "அன்பு " * 100}
            for p in (1, 2) for i in (1, 2, 3)]
    store.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return store


def test_chapter_plan_rotates_parts_and_never_repeats(tmp_path):
    store = _store(tmp_path)
    calls = []

    def judge(system, user, schema):  # every chapter suitable except part 1 chapter 1
        calls.append(user)
        ids = [l[4:] for l in user.splitlines() if l.startswith("id: ")]
        return {"chapters": [{"id": i, "theme": "love", "summary": "s", "suitable": i != "1:p1c1.htm"} for i in ids]}

    settings = {"content": {"source": "deivathin_kural"}, "paths": {"source": store.folder}}
    h = planner.History(tmp_path / "h.json")
    first = planner.plan_day(date(2026, 10, 1), settings, h, judge)
    assert calls and first.source["id"] != "1:p1c1.htm"  # only chapters judged suitable
    assert first.source["credit"].startswith("தெய்வத்தின் குரல்,") and "அன்பு" in first.context()
    h.add({"date": "2026-10-01", "source_id": first.source["id"], "theme": "love"})
    second = planner.plan_day(date(2026, 10, 2), settings, h, judge)
    assert second.source["id"] != first.source["id"]
    assert {first.source["id"][0], second.source["id"][0]} == {"1", "2"}  # a different part each day
    again = planner.plan_day(date(2026, 10, 1), settings, h, judge)  # re-running a day keeps its chapter
    assert again.source["id"] == first.source["id"]


def test_series_settings_and_prompts():
    m, p = load_settings(), load_settings(series="periyava")
    assert m["series"]["output_prefix"] == "muruganAuto" and m["content"]["title_must_contain"] == ["முருக", "Murugan"]
    assert p["series"]["launcher"] == "periyava_short.bat" and p["content"]["spare_scripts"] == 0
    system, user = S.build_prompt(planner.Plan(date(2026, 10, 1), "love", source={
        "id": "1:a", "credit": "c", "url": "u", "title": "t", "text": "அம்மா அன்பு"}), p, [], [("a.jpg", "photo")])
    assert "Deivathin Kural" in system and "அம்மா அன்பு" in user and "{" not in system
    data = dict(GOOD, youtube_title="மகா பெரியவா அருள்வாக்கு | Mother's Love")
    assert S.validate(data, p, ["a.jpg"]) == []
    assert any("பெரியவா" in e for e in S.validate(dict(GOOD), p, ["a.jpg"]))
    assert S.tidy({"hashtags": []}, p)["hashtags"] == ["#மகாபெரியவா", "#Mahaperiyava", "#DeivathinKural"]


GOOD = {"image_id": "a.jpg", "lines": ["நாம் அம்மாவை நினைப்போம்.", "அன்பே பெரிது.", "மூன்று.", "நான்கு.",
                                       "ஐந்து.", "ஆறு."],
        "keywords": ["அன்பே"], "hook_title": "தாயன்பு", "youtube_title": "முருகன் | x x x x x", "youtube_description": "d",
        "hashtags": ["#a", "#b", "#c"], "tags": ["a", "b", "c", "d", "e"]}


def test_episode_look_overlay_keeps_murugan_identical(tmp_path):
    m, p = load_settings(), load_settings(series="periyava")
    sc = S.to_script(GOOD, "t")
    assert _episode_toml(sc, m["look"], m.get("video")) == _episode_toml(sc, m["look"])
    sc.source = {"id": "1:a", "credit": "தெய்வத்தின் குரல் — \"அம்மா\"", "url": "u"}
    (tmp_path / "episode.toml").write_text(_episode_toml(sc, p["look"], p["video"]), encoding="utf-8")
    cfg = load_config(tmp_path)
    v = cfg["voice"]  # the reference voice either way: IndicF5 directly, or FastPitch re-voiced by Seed-VC
    assert (v["engine"] == "indicf5" or v.get("convert_to")) and v["style"] == "periyava"
    assert cfg["captions"]["emphasis"] == ["அன்பே"] and cfg["talking"]["enabled"] is True
    assert cfg["paths"]["bgm"].parent.name == "assets"  # the series' own background, not Murugan's
    assert cfg["paths"]["bgm"].name != "murugan_baby.mp3"


def test_toml_writer_round_trips():
    data = {"a": {"b": 1, "c": {"d": ["x", "அ"], "e": True}}, "f": {"g": "h\"q"}}
    assert deep_merge({}, tomllib.loads(_toml(data))) == data


def test_hall_and_warmth_in_voice_filter():
    f = audio.voice_filter({"semitones": 0, "pace": 1, "formant": "preserved", "hall": 1.0, "warmth_db": 2}, 48000)
    assert "aecho=" in f and "equalizer=f=220" in f and "rubberband" not in f


def test_description_credits_source_and_says_ai_voice():
    p = load_settings(series="periyava")
    sc = S.to_script(GOOD, "t")
    sc.source = {"id": "1:a", "credit": "தெய்வத்தின் குரல், முதல் பகுதி — \"அம்மா\"", "url": "https://kamakoti.org/x"}
    d = youtube.build_description(sc, {"instagram_url": "", "support_url": ""}, p)
    assert "ஆதாரம் (Source): தெய்வத்தின் குரல்" in d and "https://kamakoti.org/x" in d
    assert "AI" in d and "ஜய ஜய சங்கர" in d and d.rstrip().endswith("#Shorts")


def test_cloned_voice_goes_to_kaggle_once_then_uses_cache(tmp_path, monkeypatch):
    ref = tmp_path / "ref.wav"
    sf.write(ref, np.zeros(2400, np.float32), 24000)
    ref.with_suffix(".txt").write_text("வணக்கம்", encoding="utf-8")
    cfg = load_config()
    cfg["voice"].update(reference=str(ref), reference_denoise=False)
    calls = []

    def fake_kernel(slug, script, work, timeout, doing=""):
        inputs = json.JSONDecoder().raw_decode(script.split("INPUTS = ", 1)[1])[0]
        calls.append(inputs["lines"])
        out = work / "out"
        out.mkdir(exist_ok=True)
        with zipfile.ZipFile(out / "voice.zip", "w") as z:
            for n, text in enumerate(inputs["lines"], 1):
                wav = tmp_path / "w.wav"
                sf.write(wav, np.sin(np.linspace(0, 900, 24000)).astype(np.float32) * 0.5, 24000)
                z.write(wav, f"line_{n:02d}.wav")
                z.writestr(f"line_{n:02d}.json", json.dumps(
                    {"sample_rate": 24000, "duration": 1.0, "words": [[w, 0.1, 0.9] for w in text.split()]}))
        (out / "run_log.txt").write_text("done")
        return out

    monkeypatch.setattr(tts_indicf5.kaggle_talk, "run_kernel", fake_kernel)
    cache, work = Cache(tmp_path / "cache"), tmp_path / "work"
    work.mkdir()
    lines = tts_indicf5.synthesize_lines(["ஒன்று இரண்டு.", "மூன்று."], cfg, cache, work)
    assert calls == [["ஒன்று இரண்டு.", "மூன்று."]] and [w.text for w in lines[0].words] == ["ஒன்று", "இரண்டு."]
    tts_indicf5.synthesize_lines(["ஒன்று இரண்டு.", "புதிது."], cfg, cache, work)
    assert calls[-1] == ["புதிது."]  # only the new line goes back to Kaggle


def test_pictures_rest_ten_days_then_come_back(tmp_path):
    from autopilot import library

    pics = [library.Picture(tmp_path / f"p{i}.png", f"d{i}", {}) for i in range(6)]
    usage = {"d0": ["2026-10-01"], "d1": ["2026-09-25"], "d2": ["2026-09-20"]}  # d3-d5 never used
    ids = lambda **kw: {p.digest for p in library.candidates(pics, usage, None, 12, seed=1, **kw)}
    assert ids(rest_days=10, today="2026-10-03") == {"d2", "d3", "d4", "d5"}   # d0, d1 used in the last 10 days
    assert "d1" in ids(rest_days=10, today="2026-10-06")                       # rested long enough: back
    assert ids() == {f"d{i}" for i in range(6)}                                # no rest rule: all offered
    few = library.candidates(pics[:2], usage, None, 12, seed=1, rest_days=10, today="2026-10-03")
    assert [p.digest for p in few] == ["d1", "d0"]   # too few pictures to rest: longest-rested first, not none


def test_shared_history_merges_both_sides_once():
    from autopilot import sync

    a = [{"date": "2026-10-03", "made_at": "t1", "video_id": "x"}, {"date": "2026-10-04", "made_at": "t3"}]
    b = [{"date": "2026-10-03", "made_at": "t1", "video_id": "x"}, {"date": "2026-10-04", "made_at": "t2", "video_id": "y"}]
    merged = sync.merge_histories(a, b)
    assert [r["made_at"] for r in merged] == ["t1", "t2", "t3"]   # nothing lost, nothing doubled, in order
    assert planner.History.__new__(planner.History) is not None


def test_each_series_has_its_own_scratch_folder_and_kaggle_notebook(tmp_path):
    """Two series run on the same date (even at the same moment) must not share any file."""
    from shorts.pipeline import work_folder

    cfg = load_config()
    eps = cfg["paths"]["episodes"]
    murugan, periyava = work_folder(cfg, eps / "auto" / "2026-10-04"), work_folder(cfg, eps / "periyava" / "2026-10-04")
    assert murugan != periyava and murugan.name == "auto_2026-10-04" and periyava.name == "periyava_2026-10-04"
    assert work_folder(cfg, eps / "my-episode").name == "my-episode"   # manual episodes keep their name
    m, p = load_settings(), load_settings(series="periyava")
    sc = S.to_script(GOOD, "t")
    (tmp_path / "m").mkdir(); (tmp_path / "p").mkdir()
    (tmp_path / "m" / "episode.toml").write_text(_episode_toml(sc, m["look"], m.get("video")), encoding="utf-8")
    (tmp_path / "p" / "episode.toml").write_text(_episode_toml(sc, p["look"], p.get("video")), encoding="utf-8")
    cm, cp = load_config(tmp_path / "m"), load_config(tmp_path / "p")
    assert cm["talking"].get("kaggle_kernel", "murugan-talking") != cp["talking"]["kaggle_kernel"]
    # and each keeps its own voice and music
    assert cm["voice"].get("engine", "fastpitch") == "fastpitch" and cp["voice"]["engine"] == "indicf5"
    assert cm["paths"]["bgm"].name == "murugan_baby.mp3" and cp["paths"]["bgm"].name != "murugan_baby.mp3"
    assert cm["voice"]["style"] == "baby" and cp["voice"]["style"] == "periyava"


def test_chapter_choice_avoids_the_subject_of_recent_days(tmp_path):
    """Different chapters on one subject (each part opens with several on Pillaiyar) on
    consecutive days feel like repeats: the next day's chapter is on something else."""
    store = dk.Store(tmp_path / "dk")
    store.folder.mkdir()
    titles = ["விநாயகர்", "தத்துவமயமான விநாயகர்", "அம்மா", "விநாயகரும் தமிழும்"]
    rows = [{"part": 1, "index": i, "title": t, "url": f"{dk.BASE}c{i}.htm", "text": "அன்பு " * 100}
            for i, t in enumerate(titles, 1)]
    store.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    store.save_verdicts({f"1:c{i}.htm": {"theme": "t", "summary": "s", "suitable": True} for i in range(1, 5)})
    settings = {"content": {"source": "deivathin_kural"}, "paths": {"source": store.folder}}
    h = planner.History(tmp_path / "h.json")
    h.add({"date": "2026-10-04", "source_id": "1:c1.htm", "theme": "t", "title": "மகா பெரியவா | விநாயகரின் எளிமை"})
    for day in range(5, 12):   # whatever the day, yesterday's subject isn't taken again
        assert planner.plan_day(date(2026, 10, day), settings, h, None).source["title"] == "அம்மா"
    assert planner._subject_stems(["விநாயகர்"]) == planner._subject_stems(["விநாயகரின்"])


def test_blocked_title_words_are_never_chosen(tmp_path):
    store = dk.Store(tmp_path / "dk")
    store.folder.mkdir()
    rows = [{"part": 1, "index": i, "title": t, "url": f"{dk.BASE}c{i}.htm", "text": "அன்பு " * 100}
            for i, t in enumerate(["வர்ண தர்மம்", "பெண்கள் உத்தியோகம் பார்ப்பது", "அன்பு"], 1)]
    store.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    store.save_verdicts({f"1:c{i}.htm": {"theme": "t", "summary": "s", "suitable": True} for i in range(1, 4)})  # judge slipped
    skip = load_settings(series="periyava")["content"]["skip_title_words"]
    settings = {"content": {"source": "deivathin_kural", "skip_title_words": skip}, "paths": {"source": store.folder}}
    h = planner.History(tmp_path / "h.json")
    assert {planner.plan_day(date(2026, 10, d), settings, h, None).source["title"] for d in range(1, 9)} == {"அன்பு"}


def test_chapter_subject_is_read_from_the_text_not_only_the_title(tmp_path):
    """"உலகுக்கெல்லாம் சொந்தமானவர்" doesn't name Pillaiyar in its title; its text does. After a
    Pillaiyar chapter, it must not be the next day's choice (2026-10-05)."""
    store = dk.Store(tmp_path / "dk")
    store.folder.mkdir()
    filler = "இது ஒரு பொதுவான வாக்கியம் என்று சொல்லலாம். "
    texts = {"விநாயகர்": "பிள்ளையார் " * 12 + filler * 20,
             "உலகுக்கெல்லாம் சொந்தமானவர்": "பிள்ளையாரை " * 9 + "பிள்ளை‌யாரின் " * 3 + filler * 20,
             "குரு பக்தி": "குருவிடம் " * 12 + filler * 20}
    rows = [{"part": 1, "index": i, "title": t, "url": f"{dk.BASE}c{i}.htm", "text": x} for i, (t, x) in enumerate(texts.items(), 1)]
    rows += [{"part": 2, "index": i, "title": f"x{i}", "url": f"{dk.BASE}d{i}.htm", "text": filler * 30} for i in range(1, 40)]
    store.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    store.save_verdicts({f"1:c{i}.htm": {"theme": "t", "summary": "s", "suitable": True} for i in range(1, 4)})
    settings = {"content": {"source": "deivathin_kural"}, "paths": {"source": store.folder}}
    h = planner.History(tmp_path / "h.json")
    h.add({"date": "2026-10-04", "source_id": "1:c1.htm", "theme": "t", "title": "மகா பெரியவா | எளிமை"})
    for day in range(5, 12):
        assert planner.plan_day(date(2026, 10, day), settings, h, None).source["title"] == "குரு பக்தி"
