"""One click: sign-in check -> topic -> picture + script (written for that picture, reviewed)
-> video (shorts engine) -> scheduled upload."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time as time_module
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from autopilot import library, planner, writer, youtube
from autopilot.bank import Bank
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


def _judger(settings: dict):
    """(system, user, schema) -> dict on Gemini's free tier, for judging source chapters."""
    describe = _describer(settings)
    return lambda system, user, schema: describe(system, user, schema, None)


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


def _write_patiently(plan, settings: dict, history, pictures, interactive: bool) -> tuple[Script, bool]:
    """Returns (script, fresh). Unattended runs wait out short outages; if every writer stays
    down, a spare reviewed script from the bank is used instead of losing the day. A manual
    click doesn't wait: it goes straight to the bank."""
    tries = 1 if interactive else 1 + int(settings["schedule"].get("outage_retries", 1))
    wait = int(settings["schedule"].get("outage_wait_minutes", 10))
    for attempt in range(1, tries + 1):
        try:
            return writer.write_script(plan, settings, history.recent_titles(20), pictures), True
        except writer.NoPublishableScript:
            raise
        except RuntimeError as e:
            if attempt == tries:
                spare = Bank(settings["paths"]["bank"]).take()
                if spare:
                    log.warning("  all writers unavailable (%s); using a spare script instead", str(e).splitlines()[0][:120])
                    return spare[0], False
                raise RuntimeError(f"{e} -- and there's no spare script in the bank yet") from e
            log.warning("  all writers unavailable (%s); waiting %d min before retry %d/%d",
                        str(e).splitlines()[0][:120], wait, attempt, tries - 1)
            time_module.sleep(wait * 60)
    raise AssertionError("unreachable")


def _top_up_bank(plan, settings: dict, history, pictures, day) -> None:
    """On a day the writer works, add one spare script for a future theme (best effort)."""
    bank = Bank(settings["paths"]["bank"])
    if bank.size() >= int(settings["content"].get("spare_scripts", 3)):
        return
    avoid = {plan.theme, *bank.themes(), *history.recent_themes(settings["content"]["recent_topics_to_avoid"])}
    themes = [t for t in settings["content"]["themes"] if t not in avoid] or settings["content"]["themes"]
    theme = themes[(day.toordinal() * 7) % len(themes)]
    try:
        spare = writer.write_script(planner.Plan(day, theme), settings, history.recent_titles(20), pictures)
    except (RuntimeError, ProviderError) as e:
        log.info("  couldn't write a spare script today (%s); will try next time", str(e).splitlines()[0][:100])
        return
    bank.add(spare, theme, day)
    log.info("  saved a spare script for bad days (theme: %s; bank: %d)", theme, bank.size())


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """One autopilot run at a time (e.g. a double-click while the scheduled run is making the
    2-hour talking head). A lock left behind by a crash or power cut is ignored, because its
    process is no longer alive."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        import psutil

        if self.path.exists():
            try:
                info = json.loads(self.path.read_text(encoding="utf-8"))
                if psutil.pid_exists(info["pid"]) and info["pid"] != os.getpid():
                    raise AlreadyRunning(f"another autopilot run is already working (started {info['started']})")
            except (ValueError, KeyError):
                pass  # unreadable lock: treat as stale
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"pid": os.getpid(), "started": datetime.now().strftime("%d %b %H:%M")}),
                             encoding="utf-8")
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def _free_output_path(path: Path) -> Path:
    """Windows locks a video while it's open in a player (e.g. after a preview), and the new
    video then can't replace it. If the old one is locked, write the new one next to it."""
    if not path.exists():
        return path
    try:
        with open(path, "r+b"):
            return path  # writable: it can be replaced as usual
    except PermissionError:
        n = 2
        while (alt := path.with_name(f"{path.stem}_v{n}{path.suffix}")).exists():
            try:
                with open(alt, "r+b"):
                    return alt
            except PermissionError:
                n += 1
        log.warning("  %s is open in another program (e.g. a video player); saving as %s", path.name, alt.name)
        return alt


def _write_if_changed(path: Path, text: str) -> None:
    """Rewriting an identical file would make the finished video look out of date and
    trigger a needless re-render; only write when the content actually changes."""
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _toml(data: dict, prefix: str = "") -> str:
    """Minimal TOML writer for plain nested tables (str / number / bool / list values)."""
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    out = f"[{prefix}]\n" if prefix and scalars else ""
    out += "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in scalars.items())
    for k, v in data.items():
        if isinstance(v, dict):
            out += ("\n" if out else "") + _toml(v, f"{prefix}.{k}" if prefix else k)
    return out


def _episode_toml(script: Script, look: dict, video: dict | None = None) -> str:
    """Turns on the autopilot's look for this episode only (config.toml defaults stay off, so
    the manual workflow is unchanged). `video`: the series' own look ([video] in its settings),
    written into the episode as overrides; "{source}" in its texts becomes the retold chapter."""
    if video:
        from shorts.config import deep_merge

        credit = json.dumps(script.source.get("credit", ""), ensure_ascii=False)[1:-1]
        video = json.loads(json.dumps(video, ensure_ascii=False).replace("{source}", credit))
        return _toml(deep_merge(video, tomllib.loads(_episode_toml(script, look))))
    keywords = ", ".join(json.dumps(k, ensure_ascii=False) for k in script.keywords)
    loop = look.get("loop", True)
    return (f"[episode]\ntitle = {json.dumps(script.hook_title, ensure_ascii=False)}\n\n"
            f"[captions]\nemphasis = [{keywords}]\n\n"
            f"[effects.kenburns]\nloop = {str(loop).lower()}\n\n"
            f"[effects.glow_pulse]\nenabled = {str(look.get('glow_pulse', True)).lower()}\n\n"
            # Open on the picture itself (the first frame is what stops the scroll) and don't fade
            # to black at the end, which would break the seamless loop.
            f"[effects.fade]\nenabled = {str(not loop).lower()}\n\n"
            # Murugan's lips move with the words (SadTalker; slow, cached)
            f"[talking]\nenabled = {str(look.get('talking', True)).lower()}\n")


def run(day: date | None = None, upload: bool = True, publish_now: bool = False, force: bool = False,
        interactive: bool = True, series: str = "murugan") -> dict:
    settings = load_settings(series=series)
    day = day or date.today()
    try:
        with RunLock(settings["paths"]["episodes"] / ".running.lock"):
            return _run(settings, day, upload, publish_now, force, interactive)
    except AlreadyRunning as e:
        log.info("Nothing to do: %s. It will finish on its own.", e)
        return {"skipped": str(e)}


def _run(settings: dict, day: date, upload: bool, publish_now: bool, force: bool, interactive: bool) -> dict:
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
                    name, bat = settings["series"]["title"], settings["series"]["launcher"]
                    msg = (f"YouTube needs your approval to upload today's {name}.\n\n"
                           "Approve now? (Yes opens the Google page in your browser; the video uploads right after.)")
                    notify(f"{name}: approve YouTube", f"Click Yes on the popup, or double-click {bat}.")
                    ask(f"{name}: approve YouTube", msg, yes_command=str(ROOT / bat), workdir=str(ROOT))

        with timer.stage("plan"):
            plan = planner.plan_day(day, settings, history, judge=_judger(settings))
            log.info("  %s", f"{plan.source['credit']} ({plan.theme})" if plan.source else plan.context())

        script_path = ep_dir / "script.json"
        spare_candidates = None
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
                offered = [(p.id, p.summary()) for p in cands]
                script, fresh = _write_patiently(plan, settings, history, offered, interactive)
                if fresh:
                    spare_candidates = offered
                elif script.image_id not in {p.id for p in cands}:
                    # a spare written for a picture that's gone or was just used: take the least-used one
                    log.info("  the spare's picture %s isn't available today; using %s", script.image_id, cands[0].id)
                    script.image_id = cands[0].id
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
        _write_if_changed(ep_dir / "episode.toml", _episode_toml(script, settings.get("look", {}), settings.get("video")))

        prefix = settings["series"]["output_prefix"]
        out = _free_output_path(settings["paths"]["output"] / f"{prefix}_{day.isoformat()}.mp4")
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

                bgm = settings.get("video", {}).get("paths", {}).get("bgm", "")
                if bgm.endswith("tanpura_drone.flac") and not (ROOT / bgm).exists():
                    from shorts.effects.drone import tanpura

                    tanpura(ROOT / bgm)  # synthesised once (~20 s), then reused
                out.parent.mkdir(parents=True, exist_ok=True)  # the engine only creates its own default folder
                make_short(ep_dir, out_date=day.isoformat(), output=out)
                stamp.write_text(fingerprint)

        record = {"date": day.isoformat(), "theme": plan.theme, "title": script.youtube_title,
                  "writer": script.provider, "image": script.image_id, "image_digest": digest, "video": str(out),
                  "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if script.source:
            record["source_id"] = script.source["id"]  # this chapter isn't retold again
        if upload and signed_in:
            with timer.stage("upload"):
                when = None if publish_now else youtube.publish_time(datetime.now(timezone.utc), settings)
                video_id = youtube.upload(out, script, settings, when, interactive)
                record.update(video_id=video_id, publish_at=when.isoformat() if when else "now")
                local = when.astimezone(youtube.IST).strftime("%d %b %H:%M IST") if when else "now"
                log.info("✅ Uploaded https://youtu.be/%s -- goes public %s", video_id, local)
                if not interactive:
                    notify(f"{settings['series']['title']} scheduled", f"{script.youtube_title} -- public {local}")
        elif upload:
            record["pending_upload"] = True
            log.info("⏸ Video ready: %s. Double-click %s to approve YouTube and upload it.", out,
                     settings["series"]["launcher"])
        else:
            log.info("✅ Made %s (upload skipped)", out)
        history.add(record)
        if spare_candidates:  # the writer worked today: keep a spare for a day when it won't
            _top_up_bank(plan, settings, history, spare_candidates, day)
        log.info("%s", timer.summary())
        return record
    except BaseException as e:  # also Ctrl+C / closing the window: say so in the day's log
        reason = "stopped from outside (window closed or Ctrl+C)" if isinstance(e, KeyboardInterrupt) else str(e)
        log.error("Autopilot stopped: %s", reason.splitlines()[0][:300] if reason else type(e).__name__)
        raise
    finally:
        log.removeHandler(handler)
        handler.close()
