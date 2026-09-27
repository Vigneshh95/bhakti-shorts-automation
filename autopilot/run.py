"""One click: sign-in check -> topic -> picture + script (written for that picture, reviewed)
-> video (shorts engine) -> scheduled upload."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time as time_module
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from autopilot import library, planner, writer, youtube
from autopilot.http import ProviderError
from autopilot.notify import ask, notify
from autopilot.script import Script
from autopilot.settings import load_settings
from shorts.config import ROOT
from shorts.log import StageTimer, log


def _file_log(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    log.addHandler(h)
    return h


def _describer(settings: dict):
    """Describes new pictures with Gemini's vision model (free tier), trying the fallback
    models if one is overloaded or out of today's quota."""
    from autopilot.providers import gemini

    backups = settings["models"].get("gemini_text_fallback") or []
    models = [settings["models"]["gemini_text"], *([backups] if isinstance(backups, str) else backups)]

    def describe(system, user, schema, images):
        last = None
        for model in models:
            try:
                return gemini.complete_json(model, system, user, schema, images=images)
            except ProviderError as e:
                last = e
        raise last

    return describe


def _write_patiently(plan, settings: dict, history, pictures, interactive: bool) -> Script:
    """Unattended runs wait out temporary outages (e.g. "model overloaded") instead of losing
    the day; a manual click fails fast so nobody sits watching a console."""
    tries = 1 if interactive else 1 + int(settings["schedule"].get("outage_retries", 3))
    wait = int(settings["schedule"].get("outage_wait_minutes", 10))
    for attempt in range(1, tries + 1):
        try:
            return writer.write_script(plan, settings, history.recent_titles(20), pictures)
        except writer.NoPublishableScript:
            raise
        except RuntimeError as e:
            if attempt == tries:
                raise
            log.warning("  all writers unavailable (%s); waiting %d min before retry %d/%d",
                        str(e).splitlines()[0][:120], wait, attempt, tries - 1)
            time_module.sleep(wait * 60)
    raise AssertionError("unreachable")


def _write_if_changed(path: Path, text: str) -> None:
    """Rewriting an identical file would make the finished video look out of date and
    trigger a needless re-render; only write when the content actually changes."""
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _episode_toml(script: Script, look: dict) -> str:
    """Turns on the autopilot's look for this episode only (config.toml defaults stay off, so
    the manual workflow is unchanged)."""
    keywords = ", ".join(json.dumps(k, ensure_ascii=False) for k in script.keywords)
    loop = look.get("loop", True)
    return (f"[episode]\ntitle = {json.dumps(script.hook_title, ensure_ascii=False)}\n\n"
            f"[captions]\nemphasis = [{keywords}]\n\n"
            f"[effects.kenburns]\nloop = {str(loop).lower()}\n\n"
            f"[effects.glow_pulse]\nenabled = {str(look.get('glow_pulse', True)).lower()}\n\n"
            # Open on the picture itself (the first frame is what stops the scroll) and don't fade
            # to black at the end, which would break the seamless loop.
            f"[effects.fade]\nenabled = {str(not loop).lower()}\n")


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

        signed_in = True
        if upload:
            with timer.stage("youtube sign-in"):
                signed_in = youtube.preflight(interactive)
                if not signed_in:
                    log.warning("  YouTube sign-in has expired: making the video now; it will upload after you approve.")
                    msg = ("YouTube needs your approval to upload today's Murugan Short.\n\n"
                           "Approve now? (Yes opens the Google page in your browser; the video uploads right after.)")
                    notify("Murugan Short: approve YouTube", "Click Yes on the popup, or double-click auto_short.bat.")
                    ask("Murugan Short: approve YouTube", msg, yes_command=str(ROOT / "auto_short.bat"), workdir=str(ROOT))

        with timer.stage("plan"):
            plan = planner.plan_day(day, settings, history)
            log.info("  %s", plan.context())

        script_path = ep_dir / "script.json"
        folder = settings["paths"]["image_folder"]
        with timer.stage("picture + script"):
            script = None
            if script_path.exists() and not force:
                try:
                    saved = json.loads(script_path.read_text(encoding="utf-8"))
                    digest = saved.pop("image_digest", "")
                    script = Script(**saved)
                    if (folder / script.image_id).exists():
                        log.info("  reusing today's reviewed script and picture (%s)", script.image_id)
                    else:  # the picture was removed from the folder: choose again and write for the new one
                        log.info("  today's picture %s was removed from the folder; choosing another", script.image_id)
                        script = None
                except (ValueError, TypeError) as e:  # unreadable or from an older version: write a new one
                    log.warning("  can't reuse today's saved script (%s); writing a new one", e)
            if script is None:
                pictures = library.load(folder, describe=_describer(settings))
                if not pictures:
                    raise RuntimeError(f"No usable pictures in {folder} -- add some .jpg/.png images there.")
                cands = library.candidates(pictures, history.image_usage(), history.last_image(before=day),
                                           settings["content"]["picture_choices"], seed=day.toordinal())
                log.info("  %d pictures in the library; offering the writer %d least-used", len(pictures), len(cands))
                script = _write_patiently(plan, settings, history, [(p.id, p.summary()) for p in cands], interactive)
                digest = next(p.digest for p in cands if p.id == script.image_id)
                script_path.write_text(json.dumps({**script.to_dict(), "image_digest": digest}, ensure_ascii=False,
                                                  indent=1), encoding="utf-8")
            src = folder / script.image_id
            img_dir = ep_dir / "images"
            shutil.rmtree(img_dir, ignore_errors=True)
            img_dir.mkdir(parents=True)
            shutil.copy2(src, img_dir / f"01{src.suffix.lower()}")
            log.info("  picture: %s", script.image_id)
            log.info("  title: %s", script.youtube_title)
            for line in script.lines:
                log.info("    %s", line)

        _write_if_changed(ep_dir / "lines.txt", "\n".join(script.lines) + "\n")
        _write_if_changed(ep_dir / "episode.toml", _episode_toml(script, settings.get("look", {})))

        out = settings["paths"]["output"] / f"muruganAuto_{day.isoformat()}.mp4"
        with timer.stage("video"):
            # Fingerprint of everything the video is made from; the video is reused only if it matches
            # (timestamps aren't reliable enough to decide that).
            fingerprint = hashlib.sha256("\n".join([
                (ep_dir / "lines.txt").read_text(encoding="utf-8"),
                (ep_dir / "episode.toml").read_text(encoding="utf-8"),
                digest, script.image_id]).encode("utf-8")).hexdigest()
            stamp = out.with_suffix(".fingerprint")
            if out.exists() and not force and stamp.exists() and stamp.read_text() == fingerprint:
                log.info("  reusing today's finished video")
            else:
                from shorts.pipeline import make_short

                out.parent.mkdir(parents=True, exist_ok=True)  # the engine only creates its own default folder
                make_short(ep_dir, out_date=day.isoformat(), output=out)
                stamp.write_text(fingerprint)

        record = {"date": day.isoformat(), "theme": plan.theme, "title": script.youtube_title,
                  "writer": script.provider, "image": script.image_id, "image_digest": digest, "video": str(out),
                  "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if upload and signed_in:
            with timer.stage("upload"):
                when = None if publish_now else youtube.publish_time(datetime.now(timezone.utc), settings)
                video_id = youtube.upload(out, script, settings, when, interactive)
                record.update(video_id=video_id, publish_at=when.isoformat() if when else "now")
                local = when.astimezone(youtube.IST).strftime("%d %b %H:%M IST") if when else "now"
                log.info("✅ Uploaded https://youtu.be/%s -- goes public %s", video_id, local)
                if not interactive:
                    notify("Murugan Short scheduled", f"{script.youtube_title} -- public {local}")
        elif upload:
            record["pending_upload"] = True
            log.info("⏸ Video ready: %s. Double-click auto_short.bat to approve YouTube and upload it.", out)
        else:
            log.info("✅ Made %s (upload skipped)", out)
        history.add(record)
        log.info("%s", timer.summary())
        return record
    finally:
        log.removeHandler(handler)
        handler.close()
