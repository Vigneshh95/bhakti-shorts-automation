# Murugan Shorts

Turns a few lines of Tamil text and an image into a finished YouTube Short, with no manual
editing. The Short is 1080×1920 and includes:

- the IndicTTS voice (baby / young male / male)
- background music that ducks under the voice
- word-highlighted Tamil captions
- Ken Burns motion, golden sparkles, glow, colour grade and vignette
- a hook title, an outro and your watermark
- loudness normalised to −14 LUFS

One command, about 2 minutes on this laptop (about 45 s when the lines are already cached).

## Setup (once)

Everything is already in this folder:

| What | Where |
|---|---|
| Python environment | `.venv/` |
| FFmpeg 9.0.2 (gyan.dev essentials) | `tools/ffmpeg/` |
| Tamil TTS models | `checkpoints/` |
| Caption font (Mukta Malar, OFL) | `assets/fonts/` |

To check that everything is in place (including Intel Quick Sync hardware encoding):

```
.venv\Scripts\python.exe -m shorts check
```

Installing on a new machine: `pip install -r requirements.txt`, unzip the gyan.dev FFmpeg
"release essentials" build into `tools/ffmpeg/`, and copy `checkpoints/`.

## Make a Short

1. Create an episode folder:
   ```
   .venv\Scripts\python.exe -m shorts new 2026-09-27
   ```
2. Put one Tamil sentence per line in `episodes/2026-09-27/lines.txt`.
3. Drop one or more images in `episodes/2026-09-27/images/`. With 2+ images, the video
   switches image between sentences, using a transition.
4. Optionally set a hook title in `episodes/2026-09-27/episode.toml`.
5. Build it (the episode name alone is enough, from any folder):
   ```
   make_short.bat 2026-09-27
   ```
   or `.venv\Scripts\python.exe -m shorts make 2026-09-27 [--preset fast|balanced|best] [--voice baby|young_male|male]`

The result goes to `Final/muruganShorts_<date>.mp4`, with a matching `.txt` that the
uploader uses for the title. If a Short already exists for that date you'll see a
warning, because it will be replaced. Use `--date` or `--output` to keep both.

To upload in the same step, add `--upload`. To preview the YouTube title, tags and
description without uploading, add `--upload-dry-run`. `upload_short.bat` still works as before.

`episodes/sample-2026-03-08/` is a complete example (the lines from your 2026-03-08 Short).

## Configuration

Every setting lives in **`config.toml`**, with a comment next to each one. Any of them can be
overridden for one episode in its `episode.toml`, using the same section and key names:

```toml
[episode]
title = "பெண்மையைப் போற்று"

[voice]
style = "male"

[captions]
position_y = 0.78        # move captions down if they cover a face in this image
```

| Section | What it controls |
|---|---|
| `[run]` | preset (`fast` / `balanced` / `best`), CPU threads, low priority, keep-awake |
| `[video]` | resolution, fps, encoder (`auto` = Quick Sync, else x264), quality, output file name |
| `[voice]` | voice style, pauses between lines; `[voice.styles.*]` holds pitch, pace, EQ per style |
| `[audio]` | loudness target, music level, ducking on/off, fades |
| `[captions]` | font, size, words per caption, colours, height |
| `[effects.*]` | each effect's on/off switch and settings |
| `[presets.*]` | what `fast` and `best` change relative to `balanced` |

## How it works

```
episodes/<name>/lines.txt + images/ + episode.toml
        │
        ▼
 script     read lines, images, title
 tts        FastPitch + HiFi-GAN, one speaker ──► per-line WAV + exact word timings   [cached per line]
 audio      ONE ffmpeg graph: pitch/pace (rubberband) → EQ → music loop + ducking
            → mix; loudness measured (EBU R128)
 captions   word timings → captions.ass (word highlight, hook, outro, watermark)
 visuals    each image cover-fit to 9:16, then bake effects (grade, bloom)           [cached per image]
 render     frame generator (sub-pixel Ken Burns, transitions, sparkles, vignette)
               │ raw YUV frames through a pipe (nothing written to disk)
               ▼
            ONE ffmpeg: libass text → fades → loudness correction
                        → Intel Quick Sync H.264 + AAC → Final/…mp4
```

Why it's fast and light:
- **Static work happens once.** Colour grade and glow are baked into each image once and
  cached. Voice lines are cached individually, so editing one line re-synthesizes only
  that line. A fully cached episode never loads the voice model.
- **One pass, no re-encoding.** Frames stream straight into a single FFmpeg process that
  draws all the text and encodes on the Iris Xe's Quick Sync engine, so the CPU isn't
  used for encoding.
- **Word timings are free.** FastPitch predicts how long each character lasts. Summing
  those per word gives exact caption timing, so no separate alignment model is needed.
- **It's kind to the laptop.** It runs below normal priority, threads are capped
  (`[run] threads`), and it asks Windows not to idle-sleep mid-run.

Code layout:

```
shorts/
  __main__.py         command line: make / new / check
  pipeline.py         runs the stages, timing + peak-memory summary
  config.py           config.toml + preset + episode.toml merge
  cache.py            content-hash cache (.cache/, safe to delete)
  ffmpeg.py           FFmpeg helpers, Quick Sync detection
  stages/             script, tts, audio, captions, visuals, render
  effects/            registry + image effects (bake) + frame effects (per-frame)
tests/                one test file per stage + an end-to-end test
```

## Adding an effect

Effects declare **where** they run. That's what keeps them cheap:

| Hook | Runs | Use for |
|---|---|---|
| `bake(img)` | once per image, cached | anything static: colour, glow, sharpening |
| `prepare(ctx)` + `frame(rgb, t)` | every frame | small or local changes: sprites, a precomputed mask |

Example: a slow golden "breathing" glow at the top of the frame.

```python
# shorts/effects/overlays.py  (or a new module imported in effects/__init__.py)
@effect("halo")
class Halo(Effect):
    has_frame = True

    def prepare(self, ctx):
        yy = np.linspace(1, 0, ctx.height // 3, dtype=np.float32)[:, None, None]
        self.band = (yy ** 2 * np.array([60, 45, 10], np.float32)).astype(np.uint8)  # warm gradient

    def frame(self, rgb, t):
        k = 0.5 + 0.5 * np.sin(t * 1.2)                  # breathe
        top = rgb[: self.band.shape[0]]
        cv2.add(top, (self.band * k).astype(np.uint8), dst=top)
```

Then switch it on in `config.toml`:

```toml
[effects.halo]
enabled = true
```

Text effects (captions, hook, outro, watermark) are ASS subtitle events, created in
`shorts/stages/captions.py`.

## Tests

```
.venv\Scripts\python.exe -m pytest tests
```

The end-to-end test builds a real Short through every stage and the real FFmpeg, using a
stand-in voice so it finishes in seconds.

## Uploading

`upload_short.bat` / `autouploadmurugan.py` upload today's file from `Final/` and read the title
highlight from the `.txt` the pipeline writes next to it. `make --upload` uses the same
uploader, but uploads exactly the file just made.

Metadata fixes made in the uploader:
- corrected the description's "ஜெை" → "ஜெய் முருகன்"
- removed numbered filler openers and tags ("Daily Boost #6", "MuruganTag5")
- removed off-topic tags (தீபாவளி, திருப்பதி, கிளி…) and added Murugan-specific ones (தைப்பூசம், கந்த சஷ்டி, அறுபடை வீடு, பழனி…)
- fixed the title-template list growing on every use
