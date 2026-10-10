"""Makes a story episode's video from its reviewed script (script.json in the episode folder):

  pictures   one per scene, painted on the free Kaggle GPU (the cast's fixed looks are in every
             prompt, so the characters stay the same people)
  voices     the laptop's Tamil voice, shaped per character (child, grandmother, Murugan, narrator)
  video      the Shorts engine's own parts in 16:9: each picture is on screen exactly while its
             scene's lines are spoken, with slow camera movement, captions and music

Everything is cached: a re-run only redoes what changed."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from shorts.cache import Cache
from shorts.config import ROOT, deep_merge, load_config
from shorts.effects import enabled_effects
from shorts.log import log
from shorts.stages import audio, captions, kaggle_talk, render, tts, visuals
from shorts.stages.tts import LineAudio, Word
from stories import script as S

PICTURE_RUNNER = ROOT / "shorts" / "vendor" / "kaggle_pictures.py"
# Long videos are widescreen: every picture is painted 16:9 FOR the story (multiples of 16; the
# renderer scales it to 1920x1080). The tall 9:16 pictures of the Shorts folders are never used here.
PICTURE_SIZE = (1344, 768)

# What a story video changes in the Shorts engine's settings (config.toml stays as it is).
VIDEO = {
    "video": {"width": 1920, "height": 1080},
    "voice": {"style": "story", "line_gap_ms": 350, "lead_in_ms": 1200, "tail_ms": 2500,
              "styles": {"story": {"speaker": "female", "semitones": 0.0, "pace": 1.0, "formant": "preserved",
                                   "eq_gain_db": 0.0, "compress": True}}},
    "audio": {"bgm_db": -21.0, "duck_ratio": 3},
    "captions": {"size": 58, "words_per_caption": 6, "position_y": 0.87, "outline": 4},
    # The pictures are painted wide for the story, so nearly all of each is shown: a small margin
    # (3%) and a gentle 4% zoom, where Shorts crop 12% and zoom 8%.
    "effects": {"kenburns": {"zoom": 0.04, "pan": 0.02, "loop": False, "headroom": 1.03},
                "particles": {"count": 30, "opacity": 0.5},
                "glow_pulse": {"enabled": False},
                "watermark": {"lines": ["BrahmaNadagam"], "position_y": 0.06, "opacity": 0.45},
                "hook": {"duration_s": 2.6, "position_y": 0.14},
                "outro": {"duration_s": 2.4, "position_y": 0.14},
                "fade": {"enabled": True}},
    "talking": {"enabled": False},
}


def paint(script: dict, folder: Path, work: Path, timeout_min: int = 240, attempt: int = 0) -> list[Path]:
    """One picture per scene in <folder>/pictures (scene_01.png ...); only missing ones are painted.
    A scene that failed the check carries a "fix" note, which is added to its prompt."""
    pictures = folder / "pictures"
    pictures.mkdir(parents=True, exist_ok=True)
    paths = [pictures / f"scene_{i:02d}.png" for i in range(1, len(script["scenes"]) + 1)]
    jobs = [{"name": p.stem, "seed": 4000 + i + 1000 * attempt,
             "prompt": S.picture_prompt(sc, script.get("person_look", ""), script.get("tale_cast"))
             + (f" Important: {sc['fix']}" if sc.get("fix") else "")}
            for i, (p, sc) in enumerate(zip(paths, script["scenes"])) if not p.exists()]
    if not jobs:
        return paths
    runner = PICTURE_RUNNER.read_text(encoding="utf-8")
    size = "WIDTH, HEIGHT = 816, 1456"
    if "JOBS = []" not in runner or size not in runner:
        raise RuntimeError("the picture runner template has changed (JOBS / WIDTH, HEIGHT markers)")
    code = runner.replace("JOBS = []", "JOBS = " + json.dumps(jobs), 1).replace(
        size, f"WIDTH, HEIGHT = {PICTURE_SIZE[0]}, {PICTURE_SIZE[1]}", 1)
    log.info("  painting %d scene(s) on your Kaggle GPU (about %d min)…", len(jobs), 14 + 4 * len(jobs))
    dest = kaggle_talk.run_kernel("story-pictures", code, work, timeout_min, doing="painting")
    archive = dest / "pictures.zip"
    if not archive.exists():
        raise RuntimeError(f"The Kaggle picture run finished without pictures: {kaggle_talk._tail(dest)}")
    with zipfile.ZipFile(archive) as z:
        z.extractall(pictures)
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise RuntimeError(f"pictures not painted: {', '.join(missing)} ({kaggle_talk._tail(dest)})")
    return paths


CHECK_SYSTEM = """You check illustrations for a Tamil children's story video against what each was
meant to show. For every image (by its label) return ok and, if not ok, issue (what is wrong) and
fix: one short sentence for the painter saying what SHOULD be shown in its place, in positive words
only. Never name the unwanted thing in fix (the painter paints whatever is named): for a phone that
should be gone write "his hands are empty and open", not "remove the phone"; for a wrong forehead
mark write "three horizontal white ash lines and a small red dot on the forehead".
ok=false ONLY for clear faults that a viewer would notice:
- a person who must be there is missing, or an extra main person or a second peacock appears;
- a person's age is clearly wrong (a grown man or woman drawn as a child, or the reverse);
- what is happening contradicts the description (e.g. looking at the phone when it should be put down);
- visible writing, letters or a caption in the picture;
- badly deformed faces or hands;
- baby Murugan's forehead shows a vertical or U-shaped mark where three HORIZONTAL white ash
  stripes with a red dot were asked for.
Small differences in background, pose or colour are fine: ok=true."""

CHECK_SCHEMA = {"type": "object", "properties": {"images": {"type": "array", "items": {
    "type": "object",
    "properties": {"label": {"type": "string"}, "ok": {"type": "boolean"}, "issue": {"type": "string"},
                   "fix": {"type": "string"}},
    "required": ["label", "ok", "issue", "fix"], "additionalProperties": False}}},
    "required": ["images"], "additionalProperties": False}


def check_pictures(script: dict, paths: list[Path], settings: dict, batch: int = 6) -> dict[int, dict]:
    """Scene number -> {"issue", "fix"} for pictures that don't show what they should. Uses Gemini's
    vision (free tier). If it can't be reached the pictures are used as painted."""
    import io

    from stories import writer

    bad: dict[int, dict] = {}
    for start in range(0, len(paths), batch):
        images, notes = [], []
        for i in range(start, min(start + batch, len(paths))):
            with Image.open(paths[i]) as im:
                im = im.convert("RGB")
                im.thumbnail((896, 512))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=82)
            label = paths[i].stem
            images.append((label, buf.getvalue()))
            scene = script["scenes"][i]
            notes.append(f"{label}: {S.picture_prompt(scene, script.get('person_look', ''), script.get('tale_cast'))}")
        try:
            result = writer.ask(settings, CHECK_SYSTEM, "Meant to show:\n" + "\n".join(notes), CHECK_SCHEMA, images)
        except RuntimeError as e:
            log.warning("  the pictures couldn't be checked (%s); using them as painted", str(e)[:100])
            return bad
        for r in result.get("images", []):
            if not r.get("ok") and r.get("label", "").startswith("scene_"):
                bad[int(r["label"].split("_")[1])] = {"issue": r.get("issue", ""), "fix": r.get("fix", "")}
    return bad


def _shape(line: LineAudio, style: dict, ffmpeg: Path, cache: Cache) -> LineAudio:
    """The spoken line in its character's voice: pitch and pace changed, word timings kept in step."""
    pitch, pace = 2 ** (style["semitones"] / 12), style["pace"]
    if abs(pitch - 1) < 1e-3 and abs(pace - 1) < 1e-3:
        return line
    out, hit = cache.lookup("story_voice", cache.key("story_voice", line.wav_path, style), ".wav")
    if not hit:
        tmp = out.with_suffix(".tmp.wav")
        subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-i", str(line.wav_path), "-af",
                        f"rubberband=pitch={pitch:.5f}:tempo={pace:.5f}:formant={style.get('formant', 'preserved')}"
                        f":pitchq=quality,highpass=f=80,equalizer=f=3400:t=q:w=1.0:g={style.get('clarity_db', 2.0)}",
                        str(tmp)], check=True)
        tmp.replace(out)
    duration = sf.info(out).duration
    words = [Word(w.text, w.start / pace, w.end / pace) for w in line.words]
    return LineAudio(line.text, out, line.sample_rate, duration, words)


def _pad(line: LineAudio, seconds: float, cache: Cache) -> LineAudio:
    """The same line followed by `seconds` of silence (so the pause before the next line is longer)."""
    out, hit = cache.lookup("story_pause", cache.key("story_pause", line.wav_path, round(seconds, 2)), ".wav")
    if not hit:
        wav, sr = sf.read(line.wav_path, dtype="float32")
        sf.write(out, np.concatenate([wav, np.zeros(int(seconds * sr), np.float32)]), sr, subtype="PCM_16")
    return LineAudio(line.text, out, line.sample_rate, line.duration + seconds, line.words)


def make(folder: Path, settings: dict) -> Path:
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    cfg = deep_merge(load_config(), VIDEO)
    cfg["paths"] = {**cfg["paths"]}
    cfg["effects"]["hook"]["text"] = script["title_ta"]
    cfg["effects"]["outro"]["text"] = script["source_line_ta"]
    cache = Cache(cfg["paths"]["cache"])
    work = cfg["paths"]["cache"] / "work" / f"story_{folder.name}"
    work.mkdir(parents=True, exist_ok=True)
    ff = cfg["paths"]["ffmpeg"]

    pictures = paint(script, folder, work)
    for attempt in (1, 2):   # look at every picture; repaint the ones that don't show their scene
        marker = folder / "pictures" / f".checked_{attempt}"
        if marker.exists():
            continue
        bad = check_pictures(script, pictures, settings)
        marker.write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")
        if not bad:
            log.info("  all %d pictures show their scenes", len(pictures))
            break
        for n, why in bad.items():
            log.info("  scene %d repainted: %s", n, why["issue"][:110])
            script["scenes"][n - 1]["fix"] = why["fix"]
            pictures[n - 1].unlink(missing_ok=True)
        (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        pictures = paint(script, folder, work, attempt=attempt)
    for p in pictures:   # a tall or square picture would be cropped to a strip: refuse it
        with Image.open(p) as im:
            if im.width < im.height * 1.6:
                raise RuntimeError(f"{p.name} is {im.width}x{im.height}: story pictures must be wide (16:9)")

    # voices: every line by its speaker's voice; remember which scene each line belongs to
    home = S.home_people(script["scenes"])
    spoken, scene_of, speakers = [], [], []
    acting = settings.get("acting", {})
    if acting.get("enabled"):
        # Acted voices: each line spoken as its character with the feeling of the moment (stories/voice.py)
        from stories import voice as V
        from stories.writer import ask

        if V.directions(script, lambda system, user, schema: ask(settings, system, user, schema)):
            (folder / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=1), encoding="utf-8")
        actor = V.Actor(settings, cache, ff)
        total = sum(len(sc["lines"]) for sc in script["scenes"])
        done = 0
        for i, scene in enumerate(script["scenes"]):
            # One request speaks a character's consecutive lines in the scene (the free allowance is
            # counted in requests, and a thought spoken in one breath sounds more natural anyway).
            turns: list[list[dict]] = []
            for line in scene["lines"]:
                if turns and turns[-1][0]["speaker"] == line["speaker"]:
                    turns[-1].append(line)
                else:
                    turns.append([line])
            for turn in turns:
                role = S.voice_for(turn[0]["speaker"], script.get("tale_cast"), acting["voices"], home)
                if len(turn) > 1 and all(actor.made(l["text"], role, l["tone"]) for l in turn):
                    parts = [(l["text"], l["tone"]) for l in turn]          # spoken one by one on an earlier run
                elif len(turn) > 1:
                    parts = [(" ".join(l["text"] for l in turn),
                              " Then: ".join(dict.fromkeys(l["tone"] for l in turn)))]
                else:
                    parts = [(turn[0]["text"], turn[0]["tone"])]
                for text, tone in parts:
                    spoken.append(actor.speak(text, role, tone))
                    scene_of.append(i)
                    speakers.append(turn[0]["speaker"])
                done += len(turn)
            log.info("  scene %d of %d spoken (%d of %d lines)", i + 1, len(script["scenes"]), done, total)
        voice = None
    else:
        voice = tts.FastPitchVoice(cfg["paths"]["checkpoints"], int(cfg["run"]["threads"]))
        for i, scene in enumerate(script["scenes"]):
            for line in scene["lines"]:
                style = S.voice_for(line["speaker"], script.get("tale_cast"), settings["voices"], home)
                raw = tts.synthesize_lines([line["text"]], style["speaker"], voice, cache)[0]
                spoken.append(_shape(raw, style, ff, cache))
                scene_of.append(i)
                speakers.append(line["speaker"])
    # Pauses that follow the sense, on top of the even gap between lines: a beat after a question,
    # a breath when someone else answers, a longer rest when the picture changes.
    # People at home answer each other quickly; the narrator, Murugan and the tale take their time.
    for k in range(len(spoken) - 1):
        chat = speakers[k] in home and speakers[k + 1] in home and scene_of[k + 1] == scene_of[k]
        extra = 0.0 if chat else 0.20
        if spoken[k].text.rstrip().endswith("?"):
            extra += 0.15 if chat else 0.35
        if spoken[k].text.rstrip().endswith(("...", "…")):
            extra += 0.30
        if speakers[k + 1] != speakers[k]:
            extra += 0.05 if chat else 0.15
        if scene_of[k + 1] != scene_of[k]:
            extra += 0.55
        if extra:
            spoken[k] = _pad(spoken[k], extra, cache)
    del voice
    aud = audio.make_audio(spoken, cfg, work)
    log.info("  %.0f s of story, %d lines, %d scenes", aud.duration, len(spoken), len(pictures))

    ass = captions.write_ass(work / "captions.ass", aud.words, aud.duration, cfg, script["title_ta"])

    # each picture is on screen from just before its first line to just before the next scene's
    effects = enabled_effects(cfg["effects"])
    images = [visuals.bake_image(p, cfg, effects, cache) for p in pictures]
    starts = []
    for i in range(len(images)):
        first = scene_of.index(i)
        starts.append(0.0 if i == 0 else (aud.line_spans[first - 1][1] + aud.line_spans[first][0]) / 2)
    bounds = [*starts, aud.duration]
    kb, rng = cfg["effects"]["kenburns"], np.random.default_rng(7)
    segments = []
    for i, image in enumerate(images):
        zoom_in = i % 2 == 0
        z0, z1 = (1.0, 1.0 + kb["zoom"]) if zoom_in else (1.0 + kb["zoom"], 1.0)
        direction = rng.uniform(-1, 1, 2) * (kb["pan"] / max(kb.get("headroom", visuals.HEADROOM) - 1, 1e-6))
        segments.append(visuals.Segment(image, bounds[i], bounds[i + 1], z0, z1, (float(direction[0]), float(direction[1]))))

    out = settings["paths"]["output"] / f"{folder.name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    render.render(segments, effects, ass, aud, cfg, work, out)
    shutil.copyfile(out, folder / "video.mp4")
    log.info("✅ %s (%.0f s)", out, aud.duration)
    return out
