"""Autopilot tests -- all offline: providers, YouTube and the video engine are faked."""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from autopilot import images, planner, run as run_mod, script as S, writer, youtube
from autopilot.http import ProviderError
from autopilot.settings import load_settings

GOOD = {
    "lines": ["முருகன் சொல்வது.", "உழைப்பு உன்னை உயர்த்தும்.", "பொறுமை உன் பலம்.",
              "அன்பு உன் வழி.", "நம்பிக்கை உன் துணை.", "என் அருள் உன்னுடன்."],
    "hook_title": "உழைப்பின் வெற்றி",
    "image_prompt": "Bala Murugan with golden vel and peacock on a sacred hill at sunrise, devotional painting, no text",
    "youtube_title": "முருகன் அருள் வாக்கு | Power of Hard Work",
    "youtube_description": "உழைப்பைப் பற்றிய முருகனின் வாக்கு. Murugan's message on hard work.",
    "hashtags": ["#முருகன்", "#Murugan", "#HardWork"],
    "tags": ["Murugan", "முருகன்", "Tamil devotional", "Murugan status", "hard work Tamil", "5"],
}


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s["paths"].update(episodes=tmp_path / "ep", output=tmp_path / "out", image_folder=tmp_path / "imgs",
                      state=tmp_path / "ep" / "history.json")
    return s


def test_festival_beats_everyday_theme(settings, tmp_path):
    h = planner.History(tmp_path / "h.json")
    p = planner.plan_day(date(2026, 10, 27), settings, h)
    assert p.festival_en == "Soorasamharam" and "Soorasamharam" in p.context()
    assert planner.plan_day(date(2026, 10, 24), settings, h).festival_en == "Kanda Sashti"  # inside a date range


def test_tuesday_is_marked_and_themes_rotate(settings, tmp_path):
    h = planner.History(tmp_path / "h.json")
    tue = planner.plan_day(date(2026, 9, 29), settings, h)
    assert tue.is_tuesday and "Tuesday" in tue.context()
    h.runs = [{"theme": t} for t in settings["content"]["themes"][:-1]]
    assert planner.plan_day(date(2026, 9, 30), settings, h).theme == settings["content"]["themes"][-1]  # only unused one


def test_validation_accepts_good_and_names_each_problem(settings):
    assert S.validate(GOOD, settings) == []
    bad = dict(GOOD, lines=GOOD["lines"][:2] + ["Murugan says hello"], youtube_title="#Shorts title", hashtags=["Murugan"])
    problems = " ".join(S.validate(bad, settings))
    assert "lines" in problems and "non-Tamil" in problems and "hashtags" in problems and "must not contain" in problems


def test_tags_are_cleaned(settings):
    sc = S.to_script(GOOD, "test")
    assert "5" not in sc.tags  # numbers-only filler dropped
    assert sum(len(t) + 1 for t in sc.tags) <= 450


def test_publish_time_is_next_ist_slot(settings):
    before = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)   # 09:30 IST -> today 18:30 IST
    assert youtube.publish_time(before, settings) == datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    after = datetime(2026, 9, 27, 12, 45, tzinfo=timezone.utc)  # 18:15 IST, under 30 min lead -> tomorrow
    assert youtube.publish_time(after, settings) == datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)


def test_description_has_script_links_and_shorts_hashtag(settings):
    sc = S.to_script(GOOD, "test")
    d = youtube.build_description(sc, {"instagram_url": "https://ig.example", "support_url": ""})
    assert GOOD["lines"][1] in d and "https://ig.example" in d
    assert d.rstrip().endswith("#Shorts") and d.count("#Shorts") == 1


def test_image_falls_back_to_folder_and_skips_used(settings, tmp_path, monkeypatch):
    settings["paths"]["image_folder"].mkdir()
    for n in ("a.png", "b.png"):
        Image.new("RGB", (900, 1600), "orange").save(settings["paths"]["image_folder"] / n)
    monkeypatch.setattr(images, "_ai_image", lambda *a: (_ for _ in ()).throw(ProviderError("billing not enabled")))
    path, source = images.get_image(settings, "prompt", tmp_path / "out", used_folder_images={"a.png"})
    assert source == "folder:b.png" and path.exists()


def test_writer_retries_with_feedback_then_passes(settings, monkeypatch):
    calls = []

    def fake(model, system, user, schema):
        calls.append(user)
        if schema is S.REVIEW_SCHEMA:
            return {"ok": True, "issues": []}
        return GOOD if len(calls) > 1 else dict(GOOD, lines=["English line."] * 6)

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(fake)}))
    sc = writer.write_script(planner.Plan(date(2026, 9, 27), "patience"), settings, [])
    assert sc.lines == GOOD["lines"]
    assert "non-Tamil" in calls[1]  # the exact problem was fed back


def test_writer_fails_over_to_second_provider(settings, monkeypatch):
    def down(*a):
        raise ProviderError("HTTP 503 overloaded")

    def ok(model, system, user, schema):
        return {"ok": True, "issues": []} if schema is S.REVIEW_SCHEMA else GOOD

    providers = {"gemini": down, "openai": ok}
    monkeypatch.setattr(writer, "_provider",
                        lambda name: type("P", (), {"complete_json": staticmethod(providers[name])}))
    sc = writer.write_script(planner.Plan(date(2026, 9, 27), "patience"), settings, [])
    assert sc.provider.startswith("openai")


def test_rejected_content_is_never_published(settings, monkeypatch):
    def always_rejected(model, system, user, schema):
        return {"ok": False, "issues": ["disrespectful"]} if schema is S.REVIEW_SCHEMA else GOOD

    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(always_rejected)}))
    with pytest.raises(writer.NoPublishableScript):
        writer.write_script(planner.Plan(date(2026, 9, 27), "patience"), settings, [])


def _fake_pipeline(monkeypatch, settings, uploads):
    monkeypatch.setattr(run_mod, "load_settings", lambda: settings)
    monkeypatch.setattr(writer, "_provider", lambda name: type("P", (), {"complete_json": staticmethod(
        lambda m, s, u, schema: {"ok": True, "issues": []} if schema is S.REVIEW_SCHEMA else GOOD)}))
    monkeypatch.setattr(images, "_ai_image", lambda *a: _png())
    import shorts.pipeline

    def fake_make(ep_dir, out_date=None, output=None, **k):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        assert (ep_dir / "lines.txt").read_text(encoding="utf-8").splitlines() == GOOD["lines"]
        return type("R", (), {"output": output})

    monkeypatch.setattr(shorts.pipeline, "make_short", fake_make)
    monkeypatch.setattr(youtube, "upload", lambda video, sc, s, when, interactive: uploads.append(when) or "VID123")


def _png():
    import io
    buf = io.BytesIO()
    Image.new("RGB", (900, 1600), "gold").save(buf, "PNG")
    return buf.getvalue()


def test_one_click_run_uploads_once_per_day_and_resumes(settings, monkeypatch):
    uploads = []
    _fake_pipeline(monkeypatch, settings, uploads)
    rec = run_mod.run(date(2026, 9, 27))
    assert rec["video_id"] == "VID123" and len(uploads) == 1 and uploads[0] is not None  # scheduled, not instant
    ep = settings["paths"]["episodes"] / "2026-09-27"
    assert json.loads((ep / "script.json").read_text(encoding="utf-8"))["youtube_title"] == GOOD["youtube_title"]
    assert (ep / "run.log").exists()

    run_mod.run(date(2026, 9, 27))  # e.g. the scheduled task after a manual click
    assert len(uploads) == 1  # no second upload the same day


def test_preview_run_makes_video_without_uploading(settings, monkeypatch):
    uploads = []
    _fake_pipeline(monkeypatch, settings, uploads)
    rec = run_mod.run(date(2026, 9, 28), upload=False)
    assert not uploads and "video_id" not in rec and Path(rec["video"]).exists()


def test_no_credit_errors_are_not_retried(monkeypatch):
    import io
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
    daily = _google_429(["GenerateRequestsPerDayPerProjectPerModel-FreeTier"], "20")
    assert "used up" in _quota_problem(daily)          # skip to the next model, don't retry today
    no_free = _google_429(["GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                           "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"])
    assert "enable billing" in _quota_problem(no_free)  # images: paid only
    minute = _google_429(["GenerateRequestsPerMinutePerProjectPerModel-FreeTier"], "10")
    assert _quota_problem(minute) == "per-minute"       # wait and retry
    assert _retry_delay(minute) == 56
    assert _quota_problem('{"error":{"message":"Too many requests"}}') is None
