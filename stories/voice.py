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


def _request(model: str, prompt: str, voice: str, key: str) -> bytes:
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
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

    def _pcm(self, prompt: str, voice: str) -> bytes:
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

    def made(self, text: str, role: dict, tone: str) -> bool:
        """Was this line already spoken (on an earlier run)?"""
        return self.cache.lookup("story_actor", self.cache.key("story_actor", [VERSION, text, role, tone]), ".wav")[1]

    def speak(self, text: str, role: dict, tone: str) -> LineAudio:
        """role: {"voice", "who", optional "semitones", "pace"}."""
        signature = [VERSION, text, role, tone]
        out, hit = self.cache.lookup("story_actor", self.cache.key("story_actor", signature), ".wav")
        if not hit:
            prompt = (f"You are a voice actor in a Tamil audio drama, playing {role['who']}. Direction: {tone} "
                      f"Speak in natural everyday Tamil exactly as written, like a real person and not like someone "
                      f"reading. Say only this line, nothing else:\n{text}")
            # A take far longer than the line needs is a ramble (seen: 26 s for two words): never kept.
            # Each new try costs one of the day's free requests, so two tries, then the run stops.
            for attempt in range(2):
                pcm = self._pcm(prompt, role["voice"])
                if len(pcm) / 48000 <= too_long(text):
                    break
                log.info("  a rambling take was thrown away (%.0f s for %d letters)", len(pcm) / 48000, len(text))
            else:
                raise VoiceLimit(f"no clean take for the line: {text[:40]}… -- run again later")
            raw = out.with_suffix(".raw.wav")
            with wave.open(str(raw), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm)
            pitch, pace = 2 ** (float(role.get("semitones", 0.0)) / 12), float(role.get("pace", 1.0))
            shape = (f"rubberband=pitch={pitch:.5f}:tempo={pace:.5f}:formant={role.get('formant', 'preserved')}:pitchq=quality,"
                     if abs(pitch - 1) > 1e-3 or abs(pace - 1) > 1e-3 else "")
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.06,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse,")
            tmp = out.with_suffix(".tmp.wav")
            subprocess.run([str(self.ffmpeg), "-y", "-loglevel", "error", "-i", str(raw), "-af",
                            f"{trim}{shape}highpass=f=70,aresample=24000", "-ac", "1", str(tmp)], check=True)
            tmp.replace(out)
            raw.unlink(missing_ok=True)
        info = sf.info(out)
        return LineAudio(text, out, info.samplerate, info.duration, _spread(text, info.duration))


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
