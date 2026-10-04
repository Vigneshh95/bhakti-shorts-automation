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

---

# Autopilot: fully automatic Shorts (one click)

A second, separate workflow that uses **your own pictures**. You drop devotional images into
`daily_images/`, and every day it:
1. **Picks the topic.** A listed festival first, then Tuesday (Murugan's day), then a rotating theme not used recently.
2. **Chooses the picture.** Each new picture is described once by Gemini's free vision model: what it shows, its mood, the themes it suits, and any text painted on it. Descriptions are cached, and pictures are identified by content, so renaming is free. The writer is offered the least-used pictures, never yesterday's, picks the one that fits today's message, and writes the message to match it.
3. **Writes the Tamil script and YouTube details:** title with the keyword first, description, 3–5 hashtags, tags, and 1–3 key words. Every draft is validated, then reviewed by a second AI pass for Tamil quality, respect, honesty and fit with the picture. Nothing unreviewed is published.
4. **Makes the video** with the same engine as the manual workflow, plus the autopilot look: a seamless loop (motion returns to its start, with no fade to black, so replays flow), the key words in gold, and a gentle glow "breathing" around Murugan.
5. **Uploads to YouTube**, scheduled for 18:30 IST, with the AI-content disclosure set and Tamil as the language, then adds it to your playlist.

It never changes the manual workflow. Its videos go to `Final/auto/`.

## Use it

| Action | How |
|---|---|
| Add pictures | copy .jpg/.png files into `daily_images/` (at least 700 px on the short side) |
| Paint ~20 new pictures free (Kaggle GPU, ~2 hours, about 5 min a picture) | double-click `more_pictures.bat`, then move the ones you like from `daily_images/new_pictures/` into `daily_images/` |
| **1. Preview** (make it, don't upload; opens the video) | double-click `preview_short.bat` |
| **2. Upload** (reuses the previewed video) | double-click `auto_short.bat` |
| Go public immediately | `auto_short.bat --publish-now` |
| Check keys, pictures and YouTube sign-in | `.venv\Scripts\python.exe -m autopilot check` |
| Optional: run automatically every day | `.venv\Scripts\python.exe -m autopilot schedule install` (off by default; `remove` / `status`) |

Each day's files are in `episodes/auto/<date>/`: the script, a copy of the chosen picture, and `run.log`.

From a PowerShell terminal in another folder, run the files by their full path:
`& "C:\bhakthishorts\bhakti-shorts-automation\Murugan\preview_short.bat"` (a bare `auto_short.bat` only works inside the Murugan folder).

### New pictures (more_pictures.bat)

Z-Image-Turbo (an open model; its Apache-2.0 licence allows use on a monetised channel; SDXL is the backup) paints them in your private Kaggle notebook. They match the folder's style: child Murugan, golden crown, Vel and peacock. There are 20 scenes suited to different messages, such as courage, a mother's love, festivals, knowledge, hard work and nature. Every picture shows the face clearly, facing the viewer, so the talking face works. Pictures where no face is found are dropped. Nothing goes into the daily choice until you move it into `daily_images/`. On the next run each picture is described once, and the writer matches pictures to messages from those descriptions.

## When the YouTube sign-in expires

- **Morning scheduled run:** the video is still made, and a Windows notification asks you to approve.
- **Your double-click:** `auto_short.bat` opens the Google approval page first. After you approve, the ready video uploads without being re-made.

It never uploads twice in a day. If a run stops part-way, the next one reuses that day's reviewed script and picture.

To make the sign-in last, set the Google Cloud app's publishing status to **In production** (*Google Auth Platform → Audience*). In *Testing* mode the approval expires every 7 days.

## Writers (autopilot.toml)

`writer = "gemini"` (default), `"claude"` or `"openai"`, plus a `fallback_writer`. Keys go in `.env` as `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (and `pip install anthropic`), or `OPENAI_API_KEY`. Picture descriptions always use Gemini, which is free.

Unattended resilience:
- An overloaded model switches to the next one in `gemini_text_fallback`.
- A writer that's down switches to `fallback_writer`.
- Scheduled runs wait out short outages.
- Quota and billing errors are recognised and not retried pointlessly.

The Gemini free tier allows 20 requests a day per model. A day uses 2–6, plus one per 6 new pictures the first time they're seen.

Add each year's festival dates under `[[festivals]]` in `autopilot.toml`. The AI is never asked to guess lunar-calendar dates.

## Sri Mahaperiyava series (periyava.toml)

Each day's Short retells the essence of one *Deivathin Kural* chapter in simple spoken Tamil. The voice is modelled on your sample, his lips move with the words, and the video is scheduled for 06:30 IST in its own playlist on the same channel. It runs on the same autopilot as Murugan; only `periyava.toml` differs, and the Murugan series is untouched. The design is in `PERIYAVA_PLAN.md`.

| Action | How |
|---|---|
| **Preview** (make it, don't upload; opens the video) | double-click `periyava_preview.bat` |
| **Make and upload** | double-click `periyava_short.bat` |
| Add photos | `periyava_images/`: a clear face, front-facing, works best for lip-sync |
| Voice sample | `voices/periyava_ref.wav` (10–20 s of clear speech, no music) + its exact words in `voices/periyava_ref.txt` |
| Collect or refresh the chapters | `.venv\Scripts\python.exe -m autopilot source` (once; resumes if stopped) |
| Check keys and sign-in | `.venv\Scripts\python.exe -m autopilot --series periyava check` |

**How a day is made**
1. The next unused chapter judged suitable, taking a different part each day and book order within it. Each chapter is judged once by Gemini: a practical, universal lesson → yes; caste or birth duties, detailed ritual rules, polemics or dense philosophy → no.
2. The writer gets the whole chapter and may use only its ideas. A second pass checks the script against the chapter, the Tamil, and respect.
3. The voice is made on Kaggle: IndicF5 speaks every line in the sample's voice, and an aligner times each word for the captions.
4. On the laptop the voice gets a touch slower, warmer, and a soft temple-hall echo, over a synthesised tanpura drone.
5. The talking face is made on Kaggle, as for Murugan.
6. Upload: the description credits the chapter (with the kamakoti.org link) and says plainly that this is an AI-voiced retelling. YouTube's AI flag is set.

**One-time Hugging Face setup** (IndicF5 is free but asks you to accept its terms):
1. Sign up at huggingface.co, open huggingface.co/ai4bharat/IndicF5 and accept the terms.
2. Settings → Access Tokens → create a **Read** token.
3. On kaggle.com open your notebook **periyava-voice** (it appears after the first run) → Edit → Add-ons → Secrets → add `HF_TOKEN` with that token and tick it for this notebook. The token stays in Kaggle, never in these files.

## Running every day without a click

**In the cloud (in use): GitHub Actions**, with the laptop off. The workflow "Make a Short" starts by itself every day, makes the Short (Kaggle does the voice and face as usual) and uploads it:

| Series | Starts (IST) | Goes public (IST) | Second chance if the first start failed |
|---|---|---|---|
| Murugan | 05:47 | 18:30 the same day | 08:17 |
| Mahaperiyava | 18:47 | 06:30 the next morning | 21:17 |

GitHub may start a scheduled run some minutes late. If a run fails, GitHub emails you; the run page shows why. It can also be started by hand: Actions tab → Make a Short → Run workflow.

**One shared history.** The private repository `bhakti-shorts-assets` holds the pictures, voice sample, music, chapter text and the record of what was made and uploaded. The laptop reads and writes the same record (`autopilot/sync.py`, clone in `.cache/assets_repo`), so a double-click on a .bat and the cloud run behave the same and never post twice in a day.

| | |
|---|---|
| After adding or removing pictures | double-click `send_pictures_to_cloud.bat` |
| Make today's Short yourself | the .bat files as before (the cloud's later start then does nothing) |
| Stop the cloud runs | Actions tab → Make a Short → ⋯ → Disable workflow |

Settings on GitHub (code repository → Settings → Secrets and variables → Actions): variable `ASSETS_REPO`; secrets `ASSETS_TOKEN`, `GEMINI_API_KEY`, `HF_TOKEN`, `KAGGLE_ACCESS_TOKEN`, `YT_CLIENT_SECRET_JSON`, `YT_TOKEN_JSON`. If you change a key in `.env`, change the secret too.

**The YouTube sign-in:** set the Google Cloud app to **In production** (Google Auth Platform → Audience). In *Testing* the sign-in stops working every 7 days; a cloud run then makes the video but cannot upload it, and you must sign in on the laptop and paste the new `murugan_token.json` into the `YT_TOKEN_JSON` secret.

**On the laptop instead (off):** `.venv\Scripts\python.exe -m autopilot --series murugan schedule install` (and `--series periyava`) creates daily Windows tasks; the laptop must be on. Don't run both the tasks and the cloud schedule.
