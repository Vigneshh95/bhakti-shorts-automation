"""Cloud check for the Murugan series: its voice speaks a line (with word timings), the audio
stage mixes it, and the face finder locates the face in a picture -- with the real models."""
import sys
import tempfile
from pathlib import Path

import cv2

from shorts.cache import Cache
from shorts.config import ROOT, load_config
from shorts.stages import audio, mouth, tts

cfg = load_config()
work = Path(tempfile.mkdtemp())
cache = Cache(work / "cache")
voice = tts.FastPitchVoice(cfg["paths"]["checkpoints"], 4)
lines = tts.synthesize_lines(["முருகன் அருள் என்றும் உனக்கு உண்டு."], cfg["voice"]["styles"][cfg["voice"]["style"]]["speaker"],
                             voice, cache)
assert lines[0].duration > 1 and len(lines[0].words) == 5, (lines[0].duration, lines[0].words)
print(f"OK voice: {lines[0].duration:.1f} s, {len(lines[0].words)} timed words")

cfg["paths"]["bgm"] = None
mix = audio.make_audio(lines, cfg, work)
assert mix.mix_path.exists() and mix.duration > 2
print(f"OK audio mix: {mix.duration:.1f} s (pace/pitch filter works)")

picture = work / "face.png"
img = cv2.imread(str(ROOT / "assets" / "murugan.png"))
cv2.imwrite(str(picture), cv2.resize(img, None, fx=0.5, fy=0.5))
python = Path(sys.executable)
points = mouth.find_landmarks(picture, python, ROOT / cfg["talking"]["dir"], cache)
assert points is not None and len(points) == 68, "no face found"
print("OK face finder: 68 landmarks")
