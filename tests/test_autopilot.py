"""Autopilot tests -- all offline: providers, YouTube, notifications and the video engine are faked."""
import io
import json
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from autopilot import library, planner, run as run_mod, script as S, writer, youtube
from autopilot.http import ProviderError
from autopilot.settings import load_settings

IDS = ["a.png", "b.png"]
GOOD = {
    "image_id": "b.png",
    "lines": ["முருகன் சொல்வது.", "உழைப்பு உன்னை உயர்த்தும்.", "பொறுமை உன் பலம்.",
              "அன்பு உன் வழி.", "நம்பிக்கை உன் துணை.", "என் அருள் உன்னுடன்."],
    "keywords": ["உழைப்பு", "பொறுமை"],
    "hook_title": "உழைப்பின் வெற்றி",
    "youtube_title": "முருகன் அருள் வாக்கு | Power of Hard Work",
    "youtube_description": "உழைப்பைப் பற்றிய முருகனின் வாக்கு. Murugan's message on hard work.",
    "hashtags": ["#முருகன்", "#Murugan", "#HardWork"],
    "tags": ["Murugan", "முருகன்", "Tamil devotional", "Murugan status", "hard work Tamil", "5"],
}
PICS = [("a.png", "Bala Murugan with peacock"), ("b.png", "Murugan on a hill at sunrise")]


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s["paths"].update(episodes=tmp_path / "ep", output=tmp_path / "out", image_folder=tmp_path / "pics",
                      state=tmp_path / "ep" / "history.json")
    return s


def _pic(folder: Path, name: str, color="gold", size=(900, 1600)):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(folder / name)


# --- planning ---------------------------------------------------------------------------

def test_festival_beats_everyday_theme(settings, tmp_path):
    h = planner.History(tmp_path / "h.json")
    assert planner.plan_day(date(2026, 10, 27), settings, h).festival_en == "Soorasamharam"
    assert planner.plan_day(date(2026, 10, 24), settings, h).festival_en == "Kanda Sashti"  # inside a date range


def test_tuesday_is_marked_and_themes_rotate(settings, tmp_path):
    h = planner.History(tmp_path / "h.json")
    tue = planner.plan_day(date(2026, 9, 29), settings, h)
    assert tue.is_tuesday and "Tuesday" in tue.context()
    h.runs = [{"theme": t} for t in settings["content"]["themes"][:-1]]
    assert planner.plan_day(date(2026, 9, 30), settings, h).theme == settings["content"]["themes"][-1]


# --- picture library ----------------------------------------------------------------------

def test_library_describes_new_pictures_once_and_drops_unsuitable(tmp_path):
    folder = tmp_path / "pics"
    _pic(folder, "good.jpg")
    _pic(folder, "blurry.jpg", "grey")
    _pic(folder, "tiny.png", size=(300, 300))
    calls = []

    def describe(system, user, schema, images):
        calls.append([label for label, _ in images])
        return {"images": [
            {"label": "good.jpg", "description": "Murugan with vel", "mood": "calm", "themes": ["courage"],
             "visible_text": "", "suitable": True},
            {"label": "blurry.jpg", "description": "blurry", "mood": "", "themes": [], "visible_text": "",
             "suitable": False}]}

    pics = library.load(folder, describe)
    assert [p.id for p in pics] == ["good.jpg"] and "courage" in pics[0].summary()
    assert calls == [["blurry.jpg", "good.jpg"]]  # tiny.png never sent: too small
    library.load(folder, describe)
    assert len(calls) == 1  # cached: nothing described twice
    (folder / "good.jpg").rename(folder / "renamed.jpg")
    library.load(folder, describe)
    assert len(calls) == 1  # identified by content, so renaming costs nothing


def test_library_still_works_when_descriptions_fail(tmp_path):
    folder = tmp_path / "pics"
    _pic(folder, "x.jpg")

    def down(*a):
        raise ProviderError("overloaded")

    pics = library.load(folder, down)
    assert [p.id for p in pics] == ["x.jpg"] and p_summary_is_placeholder(pics[0])


def p_summary_is_placeholder(p):
    return p.info is None and "no description" in p.summary()


def test_candidates_prefer_unused_and_skip_yesterday(tmp_path):
    pics = [library.Picture(Path(n), d, {"description": n, "mood": "", "themes": [], "visible_text": ""})
            for n, d in (("a", "A"), ("b", "B"), ("c", "C"))]
    usage = {"A": ["2026-09-01", "2026-09-10"], "B": ["2026-09-20"]}
    picked = library.candidates(pics, usage, yesterday="C", limit=2, seed=1)
    assert [p.digest for p in picked] == ["B", "A"]  # C was yesterday; B used less than A
    assert library.candidates(pics, {}, yesterday=None, limit=3, seed=1)[0].digest in {"A", "B", "C"}


# --- script -------------------------------------------------------------------------------

def test_validation_accepts_good_and_names_each_problem(settings):
    assert S.validate(GOOD, settings, IDS) == []
    bad = dict(GOOD, lines=GOOD["lines"][:2] + ["Murugan says hello"], youtube_title="#Shorts title",
               hashtags=["Murugan"], image_id="zzz.png", keywords=["இல்லாதசொல்"])
    problems = " ".join(S.validate(bad, settings, IDS))
    for expected in ("lines", "non-Tamil", "hashtags", "must not contain", "image_id", "keywords"):
        assert expected in problems


def test_image_choice_is_limited_to_todays_candidates():
    assert S.schema(IDS)["properties"]["image_id"]["enum"] == IDS


def test_writer_retries_with_feedback_then_passes(settings, monkeypatch):
    calls = []

    def fake(model, system, user, schema, images=None):
        calls.append(user)
        if schema is S.REVIEW_SCHEMA:
            assert "Chosen picture: Murugan on a hill" in user  # reviewer checks the fit with the picture
            return {"ok": True, "issues": []}
        return GOOD if len(calls) > 1 else dict(GOOD, lines=["English line."] * 6)

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(fake)}))
    sc = writer.write_script(planner.Plan(date(2026, 9, 27), "patience"), settings, [], PICS)
    assert sc.image_id == "b.png" and sc.keywords == ["உழைப்பு", "பொறுமை"]
    assert "a.png: Bala Murugan with peacock" in calls[0]  # the writer sees the pictures
    assert "non-Tamil" in calls[1]  # the exact problem was fed back


def test_writer_fails_over_to_second_provider(settings, monkeypatch):
    def down(*a, **k):
        raise ProviderError("HTTP 503 overloaded")

    def ok(model, system, user, schema, images=None):
        return {"ok": True, "issues": []} if schema is S.REVIEW_SCHEMA else GOOD

    providers = {"gemini": down, "openai": ok}
    monkeypatch.setattr(writer, "_provider",
                        lambda name: type("P", (), {"complete_json": staticmethod(providers[name])}))
    assert writer.write_script(planner.Plan(date(2026, 9, 27), "x"), settings, [], PICS).provider.startswith("openai")


def test_rejected_content_is_never_published(settings, monkeypatch):
    def rejected(model, system, user, schema, images=None):
        return {"ok": False, "issues": ["disrespectful"]} if schema is S.REVIEW_SCHEMA else GOOD

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(rejected)}))
    with pytest.raises(writer.NoPublishableScript):
        writer.write_script(planner.Plan(date(2026, 9, 27), "x"), settings, [], PICS)


# --- youtube helpers -------------------------------------------------------------------------

def test_publish_time_is_next_ist_slot(settings):
    assert youtube.publish_time(datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc), settings) == \
        datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)                   # 09:30 IST -> today 18:30
    assert youtube.publish_time(datetime(2026, 9, 27, 12, 45, tzinfo=timezone.utc), settings) == \
        datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)                   # 18:15 IST -> tomorrow


def test_description_has_script_links_and_shorts_hashtag(settings):
    d = youtube.build_description(S.to_script(GOOD, "t"), {"instagram_url": "https://ig.example", "support_url": ""})
    assert GOOD["lines"][1] in d and "https://ig.example" in d
    assert d.rstrip().endswith("#Shorts") and d.count("#Shorts") == 1


# --- full run --------------------------------------------------------------------------------

def _fake_world(monkeypatch, settings, signed_in=True):
    state = {"uploads": [], "renders": 0, "notes": [], "asks": []}
    _pic(settings["paths"]["image_folder"], "a.png", "orange")
    _pic(settings["paths"]["image_folder"], "b.png", "gold")
    monkeypatch.setattr(run_mod, "load_settings", lambda: settings)
    monkeypatch.setattr(run_mod, "_describer", lambda s: lambda sys_, u, sch, images: {"images": [
        {"label": label, "description": f"picture {label}", "mood": "calm", "themes": ["devotion"],
         "visible_text": "", "suitable": True} for label, _ in images]})
    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(
        lambda m, s, u, schema, images=None: {"ok": True, "issues": []} if schema is S.REVIEW_SCHEMA else GOOD)}))
    import shorts.pipeline

    def fake_make(ep_dir, out_date=None, output=None, **k):
        state["renders"] += 1
        state["episode"] = tomllib.loads((ep_dir / "episode.toml").read_text(encoding="utf-8"))
        state["images"] = [p.name for p in (ep_dir / "images").iterdir()]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return type("R", (), {"output": output})

    monkeypatch.setattr(shorts.pipeline, "make_short", fake_make)
    monkeypatch.setattr(youtube, "preflight", lambda interactive: signed_in or interactive)
    monkeypatch.setattr(youtube, "upload", lambda v, sc, s, when, interactive: state["uploads"].append(when) or "VID123")
    monkeypatch.setattr(run_mod, "notify", lambda title, body: state["notes"].append(title))
    monkeypatch.setattr(run_mod, "ask", lambda title, body, yes_command="", workdir="": state["asks"].append(yes_command))
    return state


def test_one_click_run_picks_picture_turns_on_the_look_and_uploads_once(settings, monkeypatch):
    st = _fake_world(monkeypatch, settings)
    rec = run_mod.run(date(2026, 9, 27))
    assert rec["video_id"] == "VID123" and len(st["uploads"]) == 1 and st["uploads"][0] is not None  # scheduled slot
    assert rec["image"] == "b.png" and st["images"] == ["01.png"]
    assert st["episode"]["captions"]["emphasis"] == ["உழைப்பு", "பொறுமை"]
    assert st["episode"]["effects"]["kenburns"]["loop"] is True and st["episode"]["effects"]["glow_pulse"]["enabled"]
    assert st["episode"]["effects"]["fade"]["enabled"] is False  # opens on the picture; loops cleanly
    assert (settings["paths"]["image_folder"] / ".library.json").exists()

    run_mod.run(date(2026, 9, 27))  # e.g. the scheduled task after a manual click
    assert len(st["uploads"]) == 1  # never twice a day


def test_expired_sign_in_still_makes_video_then_uploads_after_approval(settings, monkeypatch):
    st = _fake_world(monkeypatch, settings, signed_in=False)
    rec = run_mod.run(date(2026, 9, 27), interactive=False)  # the morning scheduled run
    assert rec.get("pending_upload") and not st["uploads"] and st["renders"] == 1
    assert st["notes"] == ["Murugan Short: approve YouTube"]
    assert st["asks"] and st["asks"][0].endswith("auto_short.bat")  # popup: "Yes" starts approval + upload

    rec2 = run_mod.run(date(2026, 9, 27), interactive=True)  # user double-clicks and approves
    assert rec2["video_id"] == "VID123" and len(st["uploads"]) == 1
    assert st["renders"] == 1  # the ready video was reused, not re-made


def test_next_day_does_not_repeat_yesterdays_picture(settings, monkeypatch):
    st = _fake_world(monkeypatch, settings)
    run_mod.run(date(2026, 9, 27))
    seen = {}

    def pick_first(m, s, u, schema, images=None):
        if schema is S.REVIEW_SCHEMA:
            return {"ok": True, "issues": []}
        seen["offered"] = schema["properties"]["image_id"]["enum"]
        return dict(GOOD, image_id=seen["offered"][0])

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(pick_first)}))
    rec = run_mod.run(date(2026, 9, 28))
    assert "b.png" not in seen["offered"] and rec["image"] == "a.png"


def test_preview_run_makes_video_without_uploading(settings, monkeypatch):
    st = _fake_world(monkeypatch, settings)
    rec = run_mod.run(date(2026, 9, 28), upload=False)
    assert not st["uploads"] and "video_id" not in rec and Path(rec["video"]).exists()


def test_empty_picture_folder_is_a_clear_error(settings, monkeypatch):
    _fake_world(monkeypatch, settings)
    for p in settings["paths"]["image_folder"].glob("*.png"):
        p.unlink()
    with pytest.raises(RuntimeError, match="No usable pictures"):
        run_mod.run(date(2026, 9, 27), upload=False)


# --- errors ------------------------------------------------------------------------------

def test_no_credit_errors_are_not_retried(monkeypatch):
    import urllib.error
    from autopilot import http

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))

    monkeypatch.setattr(http.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderError, match="no credit"):
        http.post_json("https://api.example.com/v1/x", {}, {})
    assert len(calls) == 1


def _google_429(quota_ids, value=None):
    return json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "check your plan and billing details",
                                 "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                              "violations": [{"quotaId": q, "quotaValue": value} for q in quota_ids]},
                                             {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "55s"}]}})


def test_google_quota_errors_are_classified_from_their_details():
    from autopilot.http import _quota_problem, _retry_delay
    assert "used up" in _quota_problem(_google_429(["GenerateRequestsPerDayPerProjectPerModel-FreeTier"], "20"))
    assert "enable billing" in _quota_problem(_google_429(["GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                                           "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"]))
    minute = _google_429(["GenerateRequestsPerMinutePerProjectPerModel-FreeTier"], "10")
    assert _quota_problem(minute) == "per-minute" and _retry_delay(minute) == 56
    assert _quota_problem('{"error":{"message":"Too many requests"}}') is None


# --- new engine features (opt-in) -----------------------------------------------------------

def test_loop_motion_ends_where_it_started():
    from shorts.stages import visuals
    import cv2
    yy, xx = np.mgrid[0:2150, 0:1210]
    img = np.dstack([(xx * 255 // 1210), (yy * 255 // 2150), ((xx + yy) % 256)]).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)  # smooth, like a real picture (noise exaggerates sub-pixel shifts)
    segs = visuals.plan_segments([img], [(0, 2)], 2.0, {"zoom": 0.08, "pan": 0.03, "loop": True}, seed=1)
    frames = [f for _, f in visuals.frames(segs, 1080, 1920, 10, 2.0, {"enabled": False})]
    mid = len(frames) // 2
    assert np.abs(frames[0].astype(int) - frames[-1].astype(int)).mean() < \
        np.abs(frames[0].astype(int) - frames[mid].astype(int)).mean() / 4  # last ~ first, middle clearly moved


def test_glow_pulse_brightens_the_centre_in_gold(cfg):
    import shorts.effects.overlays  # noqa: F401  (registers the effect, as enabled_effects() does)
    from shorts.effects import REGISTRY, RenderContext
    eff = REGISTRY["glow_pulse"](dict(cfg["effects"]["glow_pulse"], enabled=True))
    eff.prepare(RenderContext(1080, 1920, 25, 8.0, seed=1))
    rgb = np.full((1920, 1080, 3), 60, np.uint8)
    eff.frame(rgb, 2.0)  # peak of the 4 s pulse
    centre = rgb[800, 540].astype(int)
    corner_gain = int(rgb[10, 10].astype(int).sum()) - 180
    assert centre[0] > centre[2] > 60  # gold (red above blue) at the centre
    assert corner_gain < (centre.sum() - 180) / 10  # a soft glow: corners barely touched


def test_emphasis_words_are_gold_in_captions(cfg):
    from shorts.stages.audio import TimedWord
    from shorts.stages.captions import ass_color, build_ass
    cfg["captions"]["emphasis"] = ["உழைப்பு"]
    words = [TimedWord("உழைப்பு", 0.0, 0.4, 0), TimedWord("உயர்த்தும்.", 0.5, 0.9, 0)]
    ass = build_ass(words, 2.0, cfg, "")
    second = [l for l in ass.splitlines() if l.startswith("Dialogue: 1,")][1]  # while the 2nd word is spoken
    assert "\\1c" + ass_color(cfg["captions"]["emphasis_color"]) + "}உழைப்பு" in second


def test_removed_picture_is_replaced_instead_of_failing(settings, monkeypatch):
    st = _fake_world(monkeypatch, settings)
    run_mod.run(date(2026, 9, 27), upload=False)          # writes today's script for b.png
    (settings["paths"]["image_folder"] / "b.png").unlink()  # the user removes that picture

    def pick_offered(m, s, u, schema, images=None):
        if schema is S.REVIEW_SCHEMA:
            return {"ok": True, "issues": []}
        return dict(GOOD, image_id=schema["properties"]["image_id"]["enum"][0])

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(pick_offered)}))
    rec = run_mod.run(date(2026, 9, 27), upload=False)
    assert rec["image"] == "a.png" and st["renders"] == 2  # new picture, new script, new video


def test_hashtag_slips_are_tidied_not_rejected(settings):
    data = S.tidy(dict(GOOD, hashtags=["#Letting Go", "Murugan", "#Murugan", "#a", "#b", "#c", "#d"],
                       keywords=["உழைப்பு,"]))
    assert data["hashtags"] == ["#LettingGo", "#Murugan", "#a", "#b", "#c"]
    assert data["keywords"] == ["உழைப்பு"]
    assert S.tidy(dict(GOOD, hashtags=["#x"]))["hashtags"] == ["#x", "#முருகன்", "#Murugan"]
    assert S.validate(data, settings, IDS) == []


def test_outages_do_not_use_up_content_drafts(settings, monkeypatch):
    calls = {"n": 0}

    def flaky(model, system, user, schema, images=None):
        calls["n"] += 1
        if model != "gemini-3.6-flash":
            raise ProviderError("HTTP 503 overloaded")
        if schema is S.REVIEW_SCHEMA:
            return {"ok": True, "issues": []}
        return GOOD if "problems" in user else dict(GOOD, lines=["English."] * 6)  # 2nd draft is good

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(flaky)}))
    sc = writer.write_script(planner.Plan(date(2026, 9, 27), "x"), settings, [], PICS)
    assert sc.provider == "gemini:gemini-3.6-flash"  # two overloaded models skipped, then 2 drafts succeeded


def test_locked_old_video_gets_a_new_name(tmp_path, monkeypatch):
    old = tmp_path / "muruganAuto_2026-09-27.mp4"
    old.write_bytes(b"old")
    real_open = open

    def locked_open(p, mode="r", *a, **k):
        if Path(p) == old and "+" in mode:
            raise PermissionError("in use by video player")
        return real_open(p, mode, *a, **k)

    monkeypatch.setattr("builtins.open", locked_open)
    assert run_mod._free_output_path(old).name == "muruganAuto_2026-09-27_v2.mp4"
    monkeypatch.setattr("builtins.open", real_open)
    assert run_mod._free_output_path(old) == old  # not locked: replaced as usual
