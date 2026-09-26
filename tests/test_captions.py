from shorts.stages.audio import TimedWord
from shorts.stages.captions import ass_color, build_ass, chunk_words, ts


def _words():
    texts = ["தாயின்", "ஆசியே", "உனது", "முதல்", "வெற்றி.", "அன்பும்", "கருணையும்"]
    lines = [0, 0, 0, 0, 0, 1, 1]
    return [TimedWord(t, i * 0.5, i * 0.5 + 0.4, l) for i, (t, l) in enumerate(zip(texts, lines))]


def test_ass_colour_is_alpha_bgr():
    assert ass_color("#FFE600") == "&H0000E6FF"
    assert ass_color("#FFFFFF", 0.5) == "&H80FFFFFF"


def test_timestamp_format():
    assert ts(0) == "0:00:00.00"
    assert ts(61.237) == "0:01:01.24"


def test_chunks_respect_size_punctuation_and_lines():
    chunks = [[w.text for w in c.words] for c in chunk_words(_words(), 3)]
    assert chunks == [["தாயின்", "ஆசியே", "உனது"], ["முதல்", "வெற்றி."], ["அன்பும்", "கருணையும்"]]


def test_every_word_gets_its_own_highlighted_event(cfg):
    ass = build_ass(_words(), 5.0, cfg, "பெண்மையைப் போற்று")
    captions = [l for l in ass.splitlines() if l.startswith("Dialogue: 1,")]
    assert len(captions) == len(_words())
    assert all("\\3c&H0000E6FF" in l for l in captions)  # yellow highlight box on the current word
    assert "பெண்மையைப் போற்று" in ass  # hook
    assert "Subscribe" in ass and "BrahmaNadagam" in ass  # outro + watermark


def test_disabled_text_effects_are_left_out(cfg):
    for name in ("hook", "outro", "watermark"):
        cfg["effects"][name]["enabled"] = False
    cfg["captions"]["enabled"] = False
    ass = build_ass(_words(), 5.0, cfg, "hook")
    assert "Dialogue" not in ass
