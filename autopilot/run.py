"""One click: plan -> write + review -> image -> video (shorts engine) -> scheduled upload."""
from __future__ import annotations

import json
import logging
import time as time_module
from datetime import date, datetime, timezone
from pathlib import Path

from autopilot import images, planner, writer, youtube
from autopilot.script import Script
from autopilot.settings import load_settings
from shorts.log import StageTimer, log


def _file_log(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    log.addHandler(h)
    return h


def _write_patiently(plan, settings: dict, history, interactive: bool) -> Script:
    """Unattended runs wait out temporary outages (e.g. "model overloaded") instead of losing
    the day; a manual click fails fast so nobody sits watching a console."""
    tries = 1 if interactive else 1 + int(settings["schedule"].get("outage_retries", 3))
    wait = int(settings["schedule"].get("outage_wait_minutes", 10))
    for attempt in range(1, tries + 1):
        try:
            return writer.write_script(plan, settings, history.recent_titles(20))
        except writer.NoPublishableScript:
            raise
        except RuntimeError as e:
            if attempt == tries:
                raise
            log.warning("  all writers unavailable (%s); waiting %d min before retry %d/%d",
                        str(e).splitlines()[0][:120], wait, attempt, tries - 1)
            time_module.sleep(wait * 60)
    raise AssertionError("unreachable")


def run(day: date | None = None, upload: bool = True, publish_now: bool = False, force: bool = False,
        interactive: bool = True) -> dict:
    settings = load_settings()
    day = day or date.today()
    history = planner.History(settings["paths"]["state"])
    ep_dir = settings["paths"]["episodes"] / day.isoformat()
    handler = _file_log(ep_dir / "run.log")
    timer = StageTimer()
    try:
        already = history.uploads_on(day)
        if upload and not force and len(already) >= settings["youtube"]["max_uploads_per_day"]:
            log.info("Already uploaded today (%s) -- nothing to do. Use --force to make another.",
                     ", ".join(f"https://youtu.be/{r['video_id']}" for r in already))
            return already[-1]

        with timer.stage("plan"):
            plan = planner.plan_day(day, settings, history)
            log.info("  %s", plan.context())

        script_path = ep_dir / "script.json"
        with timer.stage("write + review"):
            if script_path.exists() and not force:
                log.info("  reusing today's reviewed script (%s)", script_path.name)
                script = Script(**json.loads(script_path.read_text(encoding="utf-8")))
            else:
                script = _write_patiently(plan, settings, history, interactive)
                script_path.write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            log.info("  title: %s", script.youtube_title)
            for line in script.lines:
                log.info("    %s", line)

        with timer.stage("image"):
            img = ep_dir / "images" / "01.png"
            if img.exists() and not force:
                source = "reused"
                log.info("  reusing today's image")
            else:
                used = {r["image_source"].split(":", 1)[1] for r in history.runs
                        if r.get("image_source", "").startswith("folder:")}
                img, source = images.get_image(settings, script.image_prompt, ep_dir / "images", used)
            log.info("  image: %s", source)

        (ep_dir / "lines.txt").write_text("\n".join(script.lines) + "\n", encoding="utf-8")
        (ep_dir / "episode.toml").write_text(f'[episode]\ntitle = {json.dumps(script.hook_title, ensure_ascii=False)}\n',
                                             encoding="utf-8")

        out = settings["paths"]["output"] / f"muruganAuto_{day.isoformat()}.mp4"
        with timer.stage("video"):
            from shorts.pipeline import make_short

            out.parent.mkdir(parents=True, exist_ok=True)  # the engine only creates its own default folder
            result = make_short(ep_dir, out_date=day.isoformat(), output=out)

        record = {"date": day.isoformat(), "theme": plan.theme, "title": script.youtube_title,
                  "writer": script.provider, "image_source": source, "video": str(result.output),
                  "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if upload:
            with timer.stage("upload"):
                when = None if publish_now else youtube.publish_time(datetime.now(timezone.utc), settings)
                video_id = youtube.upload(result.output, script, settings, when, interactive)
                record.update(video_id=video_id, publish_at=when.isoformat() if when else "now")
                local = when.astimezone(youtube.IST).strftime("%d %b %H:%M IST") if when else "now"
                log.info("✅ Uploaded https://youtu.be/%s -- goes public %s", video_id, local)
        else:
            log.info("✅ Made %s (upload skipped)", result.output)
        history.add(record)
        log.info("%s", timer.summary())
        return record
    finally:
        log.removeHandler(handler)
        handler.close()
