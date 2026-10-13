"""Acted voices for the stories: every line is spoken by Gemini's speech model as its character,
with the emotion of that moment (a shocked question, a hurt "சரி.", a teasing child).

Two steps, both on the free Gemini key the stories use:
  1. directions(): one text request reads the whole script and writes a short acting note for
     every line (who is feeling what, how the line starts and ends). Saved in script.json as "tone".
  2. speak(): one speech request per line, in the character's own voice with that note.
Lines are cached one by one, so a run stopped by the daily free limit continues the next day.
Word timings for the captions are spread over the line by word length (lines are short)."""
from __future__ import annotations

import base64
import io
import json
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import soundfile as sf

from autopilot.settings import api_key
from shorts.cache import Cache
from shorts.log import log
from shorts.stages.tts import LineAudio, Word

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERSION = 1


class VoiceLimit(RuntimeError):
    """No speech model can take more lines right now (daily free limit): run again later."""


DIRECT_SYSTEM = """You are the dialogue director of a Tamil audio drama. For every spoken line of the
script below write one short acting note in English for the voice actor (at most 25 words): the
feeling at that exact moment, the energy and pace, and how the line should start or end (rising on
a real question, trailing off on "...", flat and cold for a hurt one-word answer, a smile in the
voice for teasing). Think about what just happened in the story and who is being spoken to. People
at home speak quickly and naturally, the way families really talk; the narrator is warm and
unhurried like a storyteller by lamp light; baby Murugan is a bright, playful five-year-old boy.
Return one note for every line, in order, numbered by scene and line (both starting at 1)."""
DIRECT_SCHEMA = {"type": "object", "properties": {"notes": {"type": "array", "items": {
    "type": "object", "properties": {"scene": {"type": "integer"}, "line": {"type": "integer"}, "tone": {"type": "string"}},
    "required": ["scene", "line", "tone"], "additionalProperties": False}}}, "required": ["notes"], "additionalProperties": False}


def directions(script: dict, ask) -> bool:
    """Adds an acting note ("tone") to every line that has none. ask: (system, user, schema) -> dict.
    Returns True if the script was changed."""
    if all(line.get("tone") for scene in script["scenes"] for line in scene["lines"]):
        return False
    names = {t["id"]: f"{t['name']} ({t['kind']})" for t in script.get("tale_cast", [])}
    names["person"] = script.get("person_look", "the person of today's story").split(",")[0]
    listing = []
    for i, scene in enumerate(script["scenes"], 1):
        listing.append(f"Scene {i}: {scene['picture']}")
        for j, line in enumerate(scene["lines"], 1):
            listing.append(f"  {i}.{j} {names.get(line['speaker'], line['speaker'])}: {line['text']}")
    notes = ask(DIRECT_SYSTEM, "\n".join(listing), DIRECT_SCHEMA).get("notes", [])
    by_place = {(n["scene"], n["line"]): n["tone"].strip() for n in notes}
    for i, scene in enumerate(script["scenes"], 1):
        for j, line in enumerate(scene["lines"], 1):
            line["tone"] = by_place.get((i, j)) or line.get("tone") or "naturally, as people really talk"
    return True


def _request(model: str, prompt: str, voice, key: str) -> bytes:
    """voice: one voice name, or {speaker name in the prompt: voice name} for a two-speaker scene."""
    if isinstance(voice, dict) and len(voice) > 1:
        speech = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": name, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for name, v in voice.items()]}}
    else:
        speech = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": next(iter(voice.values())) if isinstance(voice, dict) else voice}}}
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech}}
    req = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=180))
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    audio = next((p["inlineData"] for p in parts if "inlineData" in p), None)
    if not audio:
        raise ValueError(f"no audio returned ({json.dumps(data)[:160]})")
    raw = base64.b64decode(audio["data"])
    if raw[:4] == b"RIFF":   # some models answer with a whole wav file, others with bare 24 kHz samples
        with wave.open(io.BytesIO(raw)) as w:
            return w.readframes(w.getnframes())
    return raw


class Actor:
    """Speaks lines, moving to the next speech model when one reaches its free limit."""

    def __init__(self, settings: dict, cache: Cache, ffmpeg: Path):
        self.cfg = settings["acting"]
        # Each speech model gives 10 free requests a day PER KEY. The Shorts' key has its own speech
        # allowance, which the Shorts never use (they only write text), so the stories use both.
        keys = list(dict.fromkeys(k for k in (api_key("GEMINI_API_KEY_STORIES"), api_key("GEMINI_API_KEY")) if k))
        self.models = [(model, key) for model in self.cfg["models"] for key in keys]   # best model first, on every key
        self.cache, self.ffmpeg = cache, ffmpeg
        self.last = 0.0

    def _pcm(self, prompt: str, voice) -> bytes:
        while self.models:
            model, key = self.models[0]
            for attempt in range(4):
                wait = 60 / float(self.cfg.get("requests_per_minute", 8)) - (time.time() - self.last)
                if wait > 0:
                    time.sleep(wait)
                self.last = time.time()
                try:
                    return _request(model, prompt, voice, key)
                except urllib.error.HTTPError as e:
                    text = e.read().decode("utf-8", "replace")
                    if e.code == 429 and "PerDay" not in text and attempt < 3:
                        time.sleep(35)        # the per-minute limit: wait it out
                        continue
                    if e.code in (500, 502, 503, 504) and attempt < 3:
                        time.sleep(10 * (attempt + 1))
                        continue
                    log.info("  %s has no more free lines today (HTTP %s); moving to the next", model, e.code)
                    break
                except (ValueError, OSError) as e:
                    if attempt < 2:
                        time.sleep(5)
                        continue
                    log.warning("  %s: %s", model, str(e)[:120])
                    break
            self.models.pop(0)
        raise VoiceLimit("the free speech models have reached today's limit; run again later (finished lines are kept)")

    def speak_scene(self, chunk: list[dict], names: dict[str, str], roles: dict[str, dict]) -> LineAudio:
        """One piece of a scene (see chunks()) in one request; word timings from the aligner."""
        from stories import align

        text = " ".join(l["text"] for l in chunk)
        voices = {names[sp]: roles[sp]["voice"] for sp in sorted({l["speaker"] for l in chunk}, key=lambda sp: names[sp])}
        signature = [VERSION, "scene", [(names[l["speaker"]], l["text"], l["tone"]) for l in chunk], voices,
                     {names[sp]: roles[sp]["who"] for sp in {l["speaker"] for l in chunk}}]
        out, hit = self.cache.lookup("story_actor", self.cache.key("story_actor", signature), ".wav")
        timing = out.with_suffix(".json")
        if not (hit and timing.exists()):
            prompt = scene_prompt(chunk, names, roles)
            limit = too_long(text) + 0.8 * len(chunk)        # room for the pauses between speakers
            raw = out.with_suffix(".raw.wav")
            preamble = prompt[:prompt.rindex(chr(10) * 2)]    # the directions: cut off if the voice reads them aloud
            for attempt in range(3):
                pcm = self._pcm(prompt, voices)
                with wave.open(str(raw), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm)
                span = line_span(raw, preamble, text) if len(pcm) / 48000 <= limit + 60 else None
                if span and span[1] - span[0] <= limit:
                    break
                log.info("  a bad take was thrown away (%.0f s for %d letters)", len(pcm) / 48000, len(text))
            else:
                raw.unlink(missing_ok=True)
                raise VoiceLimit(f"no clean take for: {text[:40]}… -- run again later")
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse,")
            tmp = out.with_suffix(".tmp.wav")
            subprocess.run([str(self.ffmpeg), "-y", "-loglevel", "error", "-ss", f"{span[0]:.2f}", "-to", f"{span[1]:.2f}",
                            "-i", str(raw), "-af", f"{trim}highpass=f=70,aresample=24000", "-ac", "1", str(tmp)], check=True)
            raw.unlink(missing_ok=True)
            times, score = align.word_times(tmp, text.split())
            tmp.replace(out)
            timing.write_text(json.dumps({"words": times, "score": score}), encoding="utf-8")
        data = json.loads(timing.read_text(encoding="utf-8"))
        info = sf.info(out)
        words = [Word(w, float(a), float(b)) for w, (a, b) in zip(text.split(), data["words"])]
        return LineAudio(text, out, info.samplerate, info.duration, words)

    def made(self, text: str, role: dict, tone: str) -> bool:
        """Was this line already spoken (on an earlier run)?"""
        return self.cache.lookup("story_actor", self.cache.key("story_actor", [VERSION, text, _sound(role), tone]), ".wav")[1]

    def speak(self, text: str, role: dict, tone: str) -> LineAudio:
        """role: {"voice", "who", optional "semitones", "pace"}."""
        signature = [VERSION, text, _sound(role), tone]
        out, hit = self.cache.lookup("story_actor", self.cache.key("story_actor", signature), ".wav")
        checked = out.with_suffix(".checked")
        if hit and not checked.exists():
            # spoken before every take was checked for instructions read aloud (2026-10-13): check it now
            pre = f"You are a voice actor in a Tamil audio drama, playing {role['who']}. Direction: {tone} Say only this line:"
            span = line_span(out, pre, text)
            if span is None:
                out.unlink()
                hit = False
            elif span[0] > 0:
                tmp = out.with_suffix(".tmp.wav")
                subprocess.run([str(self.ffmpeg), "-y", "-loglevel", "error", "-ss", f"{span[0]:.2f}", "-to", f"{span[1]:.2f}",
                                "-i", str(out), "-af", "afade=t=in:d=0.05", str(tmp)], check=True)
                tmp.replace(out)
                out.with_suffix(".words.json").unlink(missing_ok=True)
        if not hit:
            prompt = (f"You are a voice actor in a Tamil audio drama, playing {role['who']}. Direction: {tone} "
                      f"Speak in natural everyday Tamil exactly as written, like a real person and not like someone "
                      f"reading. Say only this line, nothing else:\n{text}")
            # The models sometimes say more than the line: they read their English directions aloud
            # first (seen: 30 s of instructions before a 6 s line), or ramble. Every take is measured
            # against the text: just the line is kept, cut out of the take; a take in which the line
            # can't be found cleanly is thrown away and tried again in the plain "Say <how>: <line>"
            # form. Each try costs one of the day's free requests: three tries, then the run moves on.
            plain = f"Say this Tamil line as {role['who'].split(':')[0]} would, {tone[0].lower()}{tone[1:]}: {text}"
            raw = out.with_suffix(".raw.wav")
            for attempt in range(3):
                used = prompt if attempt == 0 else plain
                pcm = self._pcm(used, role["voice"])
                with wave.open(str(raw), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm)
                span = line_span(raw, used[:-len(text)], text)
                if span:
                    break
                log.info("  a bad take was thrown away (%.0f s for %d letters)", len(pcm) / 48000, len(text))
            else:
                raw.unlink(missing_ok=True)
                raise VoiceLimit(f"no clean take for the line: {text[:40]}… -- run again later")
            pitch, pace = 2 ** (float(role.get("semitones", 0.0)) / 12), float(role.get("pace", 1.0))
            shape = (f"rubberband=pitch={pitch:.5f}:tempo={pace:.5f}:formant={role.get('formant', 'preserved')}:pitchq=quality,"
                     if abs(pitch - 1) > 1e-3 or abs(pace - 1) > 1e-3 else "")
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse,")
            tmp = out.with_suffix(".tmp.wav")
            subprocess.run([str(self.ffmpeg), "-y", "-loglevel", "error", "-ss", f"{span[0]:.2f}", "-to", f"{span[1]:.2f}",
                            "-i", str(raw), "-af", f"{trim}{shape}highpass=f=70,aresample=24000", "-ac", "1", str(tmp)], check=True)
            tmp.replace(out)
            raw.unlink(missing_ok=True)
        checked.touch()
        return LineAudio(text, out, sf.info(out).samplerate, sf.info(out).duration, timed_words(out, text))


def chunks(lines: list[dict], names: dict[str, str], max_chars: int = 420) -> list[list[dict]]:
    """A scene's lines in pieces that one speech request can perform: at most two different
    speakers (the speech models' limit) and not too long. names: speaker id -> name in the prompt."""
    out: list[list[dict]] = []
    for line in lines:
        cur = out[-1] if out else None
        if (cur is None or len({names[l["speaker"]] for l in cur} | {names[line["speaker"]]}) > 2
                or sum(len(l["text"]) for l in cur) + len(line["text"]) > max_chars):
            out.append([line])
        else:
            cur.append(line)
    return out


def scene_prompt(chunk: list[dict], names: dict[str, str], roles: dict[str, dict]) -> str:
    who = sorted({l["speaker"] for l in chunk}, key=lambda sp: names[sp])
    cast = " ".join(f"{names[sp]} is {roles[sp]['who']}." for sp in who)
    how = "\n".join(f"{i}. {names[l['speaker']]}: {l['tone']}" for i, l in enumerate(chunk, 1))
    text = "\n".join(f"{names[l['speaker']]}: {l['text']}" for l in chunk)
    return (f"Perform this moment of a Tamil audio drama. {cast}\n"
            f"How each line is said, in order (directions for the actors, never spoken aloud):\n{how}\n"
            f"Speak in natural everyday Tamil exactly as written, like real people talking, with a natural pause "
            f"when the speaker changes. Say only the lines below, once, and then stop.\n\n{text}")


def line_span(wav: Path, preamble: str, text: str) -> tuple[float, float] | None:
    """Where in a take the line itself is spoken: (start, end) in seconds, or None if the take is
    not usable. A take about as long as the line needs is the line. A longer one is searched: the
    aligner is given the instructions the model was sent followed by the line, so instructions read
    aloud take up their own part of the audio and the Tamil line is found after them."""
    from stories import align

    duration = sf.info(wav).duration
    if duration < 0.03 * len(text):
        return None                                   # too short to hold the line
    if duration <= 1.9 + 0.13 * len(text):
        return 0.0, duration                          # no room for anything but the line
    pre = preamble.split()
    times, _ = align.word_times(wav, pre + text.split())
    start, end = times[len(pre)][0], times[-1][1]
    if start < 1.0:                                   # nothing was said before the line: it is just a slow take
        return (0.0, duration) if duration <= too_long(text) else None
    if not 0.03 * len(text) <= end - start <= too_long(text):
        return None
    log.info("  the voice read its instructions aloud first: %.0f s cut off, the line kept", start)
    return max(0.0, start - 0.15), min(duration, end + 0.30)


def timed_words(wav: Path, text: str) -> list[Word]:
    """When each word of the clip is spoken (the aligner), kept beside the clip; by word length if
    the aligner can't run."""
    timing = Path(wav).with_suffix(".words.json")
    if not timing.exists():
        try:
            from stories import align

            times, _ = align.word_times(wav, text.split())
            timing.write_text(json.dumps(times), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 -- captions still work, a little less exactly
            log.warning("  word timing fell back to an estimate (%s)", str(e)[:100])
            return _spread(text, sf.info(wav).duration)
    return [Word(w, float(a), float(b)) for w, (a, b) in zip(text.split(), json.loads(timing.read_text(encoding="utf-8")))]


def _sound(role: dict) -> dict:
    """What makes a line sound the way it does. Only this identifies a spoken line: a setting that
    doesn't change the sound (the list of spare voices) must not make finished lines be spoken again
    (2026-10-11: adding "alts" did, and used up a day's free lines)."""
    return {k: v for k, v in role.items() if k != "alts"}


def too_long(text: str) -> float:
    """Seconds beyond which a take cannot be just this line (slow, emotional speech is ~0.11 s a letter)."""
    return 2.5 + 0.2 * len(text)


def _spread(text: str, duration: float) -> list[Word]:
    """Word timings by word length (the captions light up word by word; lines are a few seconds)."""
    words = text.split()
    weights = [len(w.strip(".,!?…")) + 1.5 + (2.0 if w[-1:] in ",.?!…" else 0.0) for w in words]
    total, t, out = sum(weights) or 1.0, 0.0, []
    for w, weight in zip(words, weights):
        span = duration * weight / total
        out.append(Word(w, t, t + span))
        t += span
    return out
