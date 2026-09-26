import numpy as np
import soundfile as sf

from shorts.cache import Cache
from shorts.stages.audio import build_voice_track, voice_filter
from shorts.stages.tts import LineAudio, Word, _word_timings, synthesize_lines


class CharTokenizer:
    """Like the real Tamil model's tokenizer: one token per character, no cleaning."""
    text_cleaner = None

    def encode(self, ch):
        return [0]


def test_word_timings_come_from_per_character_durations():
    text = "ab cd"  # tokens: a b ' ' c d
    frames = np.array([1, 1, 2, 3, 3], float)
    words = _word_timings(CharTokenizer(), text, frames, sec_per_frame=0.1, total=1.0)
    assert [(w.text, round(w.start, 2), round(w.end, 2)) for w in words] == [("ab", 0.0, 0.2), ("cd", 0.4, 1.0)]


def test_word_timings_fall_back_to_character_share_on_token_mismatch():
    words = _word_timings(CharTokenizer(), "aa bbbb", np.ones(3), 0.1, total=3.0)  # 3 frames for 7 chars
    assert [w.text for w in words] == ["aa", "bbbb"]
    assert abs(words[0].end - 1.0) < 1e-6 and abs(words[1].end - 3.0) < 1e-6


def test_lines_are_cached_individually(tmp_path, fake_voice):
    cache = Cache(tmp_path)
    synthesize_lines(["ஒன்று இரண்டு", "மூன்று"], "female", fake_voice, cache)
    assert fake_voice.calls == 2
    synthesize_lines(["ஒன்று இரண்டு", "நான்கு"], "female", fake_voice, cache)  # one line changed
    assert fake_voice.calls == 3  # only the changed line was synthesized again
    again = synthesize_lines(["ஒன்று இரண்டு"], "female", fake_voice, cache)
    assert again[0].words[1].text == "இரண்டு"


def _line(tmp_path, name, seconds, words):
    p = tmp_path / f"{name}.wav"
    sf.write(p, np.zeros(int(seconds * 22050), np.float32), 22050)
    return LineAudio(name, p, 22050, seconds, words)


def test_voice_track_timings_land_on_the_paced_final_timeline(tmp_path):
    lines = [_line(tmp_path, "a", 1.0, [Word("a", 0.0, 1.0)]), _line(tmp_path, "b", 2.0, [Word("b", 0.5, 2.0)])]
    voice_cfg = {"lead_in_ms": 400, "line_gap_ms": 900, "tail_ms": 1000}
    pace = 0.8
    duration, words, spans = build_voice_track(lines, voice_cfg, pace, tmp_path / "v.wav")
    # speech is stretched by 1/pace; configured silences land at exactly their configured length
    assert abs(words[0].start - 0.4) < 0.01
    assert abs(spans[0][1] - (0.4 + 1.0 / pace)) < 0.01
    assert abs(words[1].start - (0.4 + 1.0 / pace + 0.9 + 0.5 / pace)) < 0.01
    assert abs(duration - (0.4 + 3.0 / pace + 0.9 + 1.0)) < 0.01
    assert words[1].line == 1


def test_voice_filter_matches_the_original_baby_preset(cfg):
    f = voice_filter(cfg["voice"]["styles"]["baby"], 48000)
    assert "rubberband=pitch=1.25992:tempo=0.83300:formant=shifted" in f  # +4 semitones, the old -t 1.2
    assert "acompressor" not in f
    male = voice_filter(cfg["voice"]["styles"]["male"], 48000)
    assert "rubberband" not in male  # neutral pitch and pace: no pitch-shift pass at all
