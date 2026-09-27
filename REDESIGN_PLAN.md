# Murugan Shorts — Redesign Plan

Status: **proposal, awaiting approval.** No code in this folder has been changed.
Date: 2026-09-26

---

## 0. Decisions already made (from you)

| Question | Your answer | What it means for the design |
|---|---|---|
| Visual style | Still image + effects (like your recent Shorts) | SadTalker talking head is dropped |
| Voice | Free, efficient, fast | Keep the local IndicTTS FastPitch voice; no paid API |
| Images | You supply them | The pipeline animates whatever images you drop in |
| Constraint | Light on laptop CPU/RAM, best possible output | Everything static is computed once; one render pass; hardware encoding |

Machine this has to run on: Intel i5-1135G7 (4 cores / 8 threads), 12 GB RAM, **Intel Iris Xe only (no NVIDIA)**, Windows 11.
That rules out CUDA-based AI video models, but Iris Xe has **Intel Quick Sync**: a hardware H.264/HEVC encoder that frees the CPU.

---

## 1. What exists today (Phase 1 findings)

### 1.1 The real pipeline

```
run_video_generation.bat
 └─ test.py --voice baby
     1. Load IndicTTS FastPitch + HiFi-GAN (CPU)
     2. Synthesize ALL lines as 'male'   → raw_male.wav     (not used for baby)
     3. Synthesize ALL lines as 'female' → raw_female.wav
     4. rubberband.exe -p 4 -t 1.2        → baby_rb.wav     (pitch +4 st, 20% SLOWER)
     5. SadTalker (separate 3.6 GB venv, CPU, 256 px) → talking-head mp4
     6. ffmpeg pad → 256x456 "9:16" mp4
 ── MANUAL STEP (video editor) ──────────────────────────────────────────
     new AI image, particles/glow, word-highlight Tamil captions, watermark
     "Subscribe & Share / BrahmaNadagam", BGM, loudness → Final/muruganShorts_<date>.mp4
     (1080x1920, 25 fps, H.264 ~8 Mbps, AAC 192k, −14.1 LUFS)
 ────────────────────────────────────────────────────────────────────────
upload_short.bat → autouploadmurugan.py → YouTube (+ playlist)
```

The pipeline is only half automated. Everything that makes the published Short look good (captions, effects, music, the 1080x1920 frame) is currently done **by hand**.

### 1.2 Baseline measurement

Measured on this laptop by running `test.py --voice baby` unchanged: 8 Tamil lines, cold start, no cache.

| Stage | Time | Notes |
|---|---|---|
| Python/torch import + TTS model load | ~31 s | |
| Synthesize 'male' (not used) | 33 s | wasted work |
| Synthesize 'female' (29.9 s of speech) | 36 s | ~1.2× slower than real time |
| rubberband pitch/tempo | 1.5 s | |
| SadTalker load + preprocessing | ~90 s | |
| SadTalker face render (448 batches × ~16.7 s) | **2 h 5 min (7,501 s)** | the bottleneck |
| Pad to 256x456 | 1.4 s | |
| **Total (automated part only)** | **2 h 8 min 33 s (7,713 s)** | |
| Peak RAM (whole process tree) | **4.7 GB** (4,766 MB) | |
| Output | 256x456, 35.8 s, 0.45 MB | still needs manual editing to become a Short |
| Manual editing | not measurable by me | the real hidden cost |

### 1.3 Problems found

**Performance / waste**
1. **SadTalker on CPU is about 98% of runtime**, and your recent published Shorts don't use the talking face.
2. Both voices are synthesized every run, though only one is used (≈33 s wasted).
3. Nothing is cached. Changing one line re-synthesizes all of them and re-loads the model.
4. Audio is processed as a chain of separate ffmpeg calls, each writing a temp WAV (EQ → reverb copy → loudnorm → BGM mix → mp3 via pydub).
5. `anlmdn` (a slow denoiser) runs on clean synthetic speech, where it does nothing useful.
6. torch runs with default threading and no `inference_mode`.

**Correctness / fragility**
7. `RB_TEMPO = 1.25 # speed up by 25%` and preset `tempo: 1.20`: rubberband `-t` is a *time* ratio, so this actually **slows speech down** 20%. Your published pacing (35.8 s) depends on this, so the new version keeps the pace but names it correctly (`pace = 0.83`).
8. The `baby` preset returns early and skips EQ, compression, loudness normalization and BGM.
9. The output is 256x456, which is not a usable Short.
10. `BASE_DIR` is hardcoded in 6 scripts. There are 5 near-duplicate copies of the pipeline (`test.py`, `test_audio.py`, `sample.py`, `sample1.py`, `murugan_voice_gen.py`) and a dead Wav2Lip script (`create_video.py`).
11. The Tamil script lines are hardcoded in Python and edited by hand each episode.
12. There is no git, no tests, and no config file.
13. **Security:** `.env`, `client_secret.json` and `murugan_token.json` sit in the project root. They must never be committed. The new `.gitignore` will exclude them.
14. The file `1.23.0` is an accidental pip log (from an unquoted `pip install numpy>=1.23.0`). It's harmless and can be deleted.

**Outdated tooling**
15. The ffmpeg on PATH is **4.2.3 from 2020**, bundled inside ImageMagick. The current release is **9.0.2 (2026-09-19)**. The old build's QSV and libass/HarfBuzz support is uncertain, and HarfBuzz is required to render Tamil text correctly.
16. moviepy, pydub, pyworld and the SadTalker env (torch 2.9 CPU + GFPGAN) would all become unnecessary.

---

## 2. Research summary (Phase 2)

| Area | Current best option | Fit for this laptop | Decision |
|---|---|---|---|
| **Encoding** | FFmpeg 9.x with Intel QSV (`h264_qsv`) via oneVPL; libx264 as fallback | Iris Xe supports it | **Use.** CPU stays free for everything else |
| **FFmpeg build** | gyan.dev "full" build 9.0.2: includes libass, HarfBuzz, librubberband, libvpl (QSV), zimg | Windows, one zip, no install | **Use** (needs your OK to download) |
| **Tamil TTS (free, local)** | AI4Bharat IndicF5 (voice cloning), Indic Parler-TTS (voice by description), your current IndicTTS FastPitch | IndicF5/Parler are large generative models; I have **not** benchmarked them on this CPU and expect them to be much slower than FastPitch | **Keep FastPitch** (fast, free, the voice you already publish). IndicF5 is an optional later experiment, gated on a benchmark |
| **Tamil TTS (paid)** | Sarvam Bulbul v3, ≈₹30 per 10k characters (≈₹1 per Short) | API | Not used (you asked for free). Could be added behind a config switch later |
| **Word timing for captions** | Forced aligners (ctc-forced-aligner / MMS-300M, 158 languages) or FFmpeg 8+'s whisper filter | Extra 300 MB+ model and CPU time | **Not needed.** FastPitch already predicts a duration for every character it speaks (`forward_tts.py:692`, character input, no blank tokens, 22050 Hz / hop 256 = 11.6 ms per frame). That gives exact word timings for free |
| **Caption rendering** | ASS subtitles rendered by libass inside FFmpeg, with HarfBuzz for Tamil shaping | Very cheap, drawn during the same pass | **Use** |
| **Ken Burns motion** | FFmpeg `zoompan` shudders because it rounds to whole pixels. The common fix (upscale to ~8000 px first) costs about 144 MB per frame. Sub-pixel affine warps avoid the shudder cheaply | | **Benchmark 3 methods in step 3** (below) and keep the fastest artifact-free one |
| **Talking head** | LivePortrait / Hallo3 / MuseTalk are all GPU-oriented; SadTalker CPU is ~2 h per Short here | No NVIDIA GPU | **Drop** (your decision) |

Sources: [FFmpeg 8.0 release (Phoronix)](https://www.phoronix.com/news/FFmpeg-8.0-Released), [gyan.dev FFmpeg builds](https://www.gyan.dev/ffmpeg/builds/), [Intel QSV + FFmpeg](https://salivity.github.io/ffmpeg/article/transcoding-video-with-ffmpeg-h264-qsv), [IndicF5](https://github.com/AI4Bharat/IndicF5), [IndicF5 vs Indic Parler-TTS](https://www.aimodels.fyi/models/huggingFace/indicf5-ai4bharat), [Sarvam pricing](https://docs.sarvam.ai/api-reference-docs/pricing), [Bulbul v3](https://www.sarvam.ai/blogs/bulbul-v3), [ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner), [MMS-300M forced aligner](https://sourceforge.net/projects/mms-300m-1130-forced-aligner/), [libass complex-script shaping via HarfBuzz](https://github.com/EngDawood/video-caption/pull/13), [zoompan jitter explanation](https://www.ffmpeg-micro.com/blog/ffmpeg-zoompan-filter-ken-burns-zoom-and-pan-without-the-jitter), [sub-pixel pan/zoom approach](https://github.com/jham2081-blip/glide-ffmpeg), [SadTalker vs LivePortrait](https://sadtalker.ai/sadtalker-vs-liveportrait), [open-source lip-sync overview 2026](https://lipsync.com/blog/open-source-lip-sync).

---

## 3. New architecture

### 3.1 Core principle: compute static things once, render moving things once

Almost everything in these Shorts is **static**: the image, its colour grade, glow, vignette and watermark.
Only three things move: camera motion, particles and captions. So:

- **Static effects are baked once** onto the image, before any frames exist. Cost is roughly zero per frame.
- **Reusable assets are cached**: the particle loop, watermark PNG, and each TTS line.
- **Motion, overlays, captions and encoding happen in one streaming pass.** No temp frames on disk and no re-encoding.

### 3.2 Pipeline

```
episodes/2026-09-27/
  lines.txt            ← one Tamil sentence per line (replaces hardcoded LINES)
  images/*.png|jpg     ← 1..N images (you supply)
  episode.toml         ← optional overrides (voice, preset, title…)
          │
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 1. SCRIPT     read + normalise lines                                 │
│ 2. TTS        FastPitch (one speaker only) per line                  │
│               → wav + per-character durations   [cached per line]    │
│               model is loaded ONLY if some line is not cached        │
│ 3. AUDIO      ONE ffmpeg filtergraph:                                │
│               concat+gaps → rubberband pitch (formant-preserved)     │
│               → pace → EQ → compressor → light reverb                │
│               → BGM loop + fade + sidechain ducking                  │
│               → loudnorm 2-pass (−14 LUFS, −1 dBTP)                  │
│               word timings scaled by the same pace factor            │
│ 4. CAPTIONS   word timings → .ass file (Tamil font, word highlight,  │
│               hook title, outro CTA)                                 │
│ 5. VISUALS    per image, once: fit 9:16, colour grade, bloom         │
│               → cached 1080x1920 (+ margin for motion)               │
│               effect overlays generated once and cached:             │
│               particle loop, vignette, watermark                     │
│ 6. RENDER     frame generator (sub-pixel Ken Burns + transitions     │
│               at sentence boundaries) ── raw frames via pipe ──►     │
│               ffmpeg: overlay particles → vignette → watermark       │
│               → subtitles(.ass) → h264_qsv (fallback libx264)        │
│               + mixed audio → Final/muruganShorts_<date>.mp4         │
│               + companion .txt (uploader already reads it for titles)│
│ 7. UPLOAD     (optional, explicit flag) existing autouploadmurugan.py│
└──────────────────────────────────────────────────────────────────────┘
```

One command: `python -m shorts make episodes/2026-09-27` (a `make_short.bat` wrapper is included).

### 3.3 Why this beats the current design

| | Today | New |
|---|---|---|
| Manual editing | Required for every video | None |
| Talking-head render | ~2 h CPU | Removed |
| TTS work | 2 speakers, every run | 1 speaker, cached per line (edit one line → re-synthesize one line) |
| Audio passes | 5+ ffmpeg/pydub calls, temp files | 1 measure pass + 1 render pass |
| Caption timing | Manual in editor | Exact, from the TTS model itself |
| Video encoding | CPU (x264) in the editor | Intel Quick Sync hardware encoder |
| Laptop load | CPU pegged for hours | Short burst, below-normal process priority, capped threads |
| Settings | Edit Python | `config.toml` + per-episode overrides |

### 3.4 What is kept, replaced, removed

**Kept**
- IndicTTS FastPitch + HiFi-GAN checkpoints and the `.venv`
- Voice presets (baby / young_male / male), same values, so the voice you publish doesn't change
- rubberband (now used through FFmpeg's built-in `rubberband` filter)
- `autouploadmurugan.py` + `config.ini` (unchanged; optional final step)

**Replaced**
- `test.py` and its 4 copies → `shorts/` package with one module per stage
- Hardcoded `LINES` → `episodes/<name>/lines.txt`
- Hardcoded paths → `config.toml` (paths relative to the repo)
- ffmpeg 4.2.3 → FFmpeg 9.0.2 full build (bundled in `tools/`, no PATH changes)
- pydub → soundfile/numpy (already installed)

**No longer used** (moved to `legacy/` or git-ignored; **nothing is deleted by me**)
- SadTalker/, .sadtalker_env/, gfpgan/ (≈4+ GB you can delete yourself later)
- moviepy, pyworld fallback, `create_video.py` (Wav2Lip), `sample*.py`, `test_audio.py`, `run_baby_video_generation.py`, `run_all_voices.py`

---

## 4. Effects system

Every effect is a small class that declares **where** it runs. This forces efficient placement by design:

| Hook | Runs | Cost | Used for |
|---|---|---|---|
| `bake(image)` | once per image, before motion | ~0 per frame | colour grade, bloom/glow, sharpen |
| `asset()` | once ever, then cached | 0 on later runs | particle loop, vignette mask, watermark PNG |
| `ffmpeg_filter()` | inside the single render pass | small, SIMD | overlay/blend, fades |
| `ass()` | libass inside the same pass | tiny | captions, titles, CTA |
| `motion(t)` | frame generator | the only per-frame Python work | Ken Burns, transitions |

Effects are switched on/off and tuned in `config.toml` per preset (`fast`, `balanced`, `best`) and can be overridden per episode.

### Built-in effects

1. **Ken Burns / subtle motion** — slow zoom-in / zoom-out / pan, randomised per image with a seed so re-renders are identical. Sub-pixel accurate (no shudder). Default 1.00→1.08 zoom over the image's duration.
2. **Transitions** (only when you provide 2+ images) — image changes on **sentence boundaries** (we know them exactly). Options: crossfade, zoom-through, soft slide. Default is crossfade, which suits devotional pacing.
3. **Animated word-highlight captions** — the current word gets a highlight box (matching your current yellow style), and each line fades/scales in. Tamil shaped correctly via HarfBuzz using an OFL Tamil font (e.g. Noto Sans Tamil / Mukta Malar). Positioned inside the **Shorts safe zone** (clear of the bottom title/channel UI and right-side buttons).
4. **Colour grade** — `.cube` LUT or built-in "warm divine" curve, **baked into the image once**.
5. **Glow / bloom** — soft highlight bloom, baked once.
6. **Particles / sparkles / light dust** — procedurally generated seamless loop (seeded), rendered once and cached, blended with *screen* mode. You can also drop your own overlay video into `assets/overlays/`.
7. **Vignette** — static mask, cached.
8. **Watermark** — "Subscribe & Share / BrahmaNadagam" text from config, cached PNG.
9. **Intro hook + outro CTA** — first ~1.5 s: title text scales/fades in ("முருகன் சொல்வது"-style hook). Last ~2 s: "Subscribe" call to action. Both are ASS animations, so they add almost nothing to render cost.
10. **Audio polish** — formant-preserving pitch shift, EQ, compressor, gentle room reverb, BGM loop with fade in/out, **automatic ducking under the voice** (sidechain), EBU R128 loudness to **−14 LUFS / −1 dBTP** (matches your current published loudness).
11. **Fade in / out** of picture and sound at start/end.

### Adding a new effect (preview of the README section)
Create `shorts/effects/my_effect.py` with a class that implements one hook (`bake`, `asset`, `ffmpeg_filter` or `ass`), register it with `@effect("my_effect")`, and enable it in `config.toml` under `[effects.my_effect]`.

---

## 5. Expected performance (reasoned estimates, to be measured)

These are **estimates**, not measurements. Each one will be replaced by a measured number in the final before/after table.

| Stage | Estimate (cold) | Estimate (re-run, cached) | Reasoning |
|---|---|---|---|
| Import + model load | ~25 s | 0 s | Model only loaded when a line isn't cached |
| TTS (one speaker, ~30 s speech) | 20–35 s | 0 s | Today 36 s; drop 2nd speaker; set torch threads to 4 physical cores + `inference_mode` |
| Audio graph | 2–4 s | 2–4 s | Two ffmpeg passes over ~40 s of audio |
| Image bake + cached assets | 5–15 s first time | ~0 s | Particle loop generated once |
| Render 1080x1920, 25 fps, ~40 s (~1000 frames) | 30–90 s | same | Frame generator + ffmpeg blend + libass + QSV. The Ken Burns method benchmark decides where in this range |
| **Total** | **~1.5–2.5 min** | **~40–100 s** | vs **2 h 8 min + manual editing** today |
| Peak RAM | ~1.5 GB (vs 4.7 GB today) | < 1 GB | FastPitch ~1.2 GB, released before render; render holds only a few frames |

Output: 1080x1920, H.264 High, yuv420p, 25 fps (same as today), AAC 48 kHz 192k, `+faststart`. Quality target is set with QSV's ICQ mode instead of a fixed 8 Mbps; still images with light motion need far less bitrate for the same quality.

---

## 6. Implementation steps (Phase 4, after approval)

Each step ends with running the pipeline and comparing against the baseline.

0. **Safety net:** `git init`, commit the current code on `main` (secrets, venvs, models and media git-ignored), then create branch `redesign`. Nothing on `main` changes after that.
1. **Tooling:** download the FFmpeg 9.0.2 full build into `tools/ffmpeg/`. Verify `h264_qsv` works on your Iris Xe and that libass renders Tamil correctly (test render).
2. **Skeleton + config + cache + logging:** `shorts/` package, `config.toml`, content-hash cache, progress output, clear errors.
3. **TTS stage:** single speaker, per-line cache, per-character durations → word timings. Test that timings sum to the audio length.
4. **Audio stage:** one filtergraph. Test loudness = −14 ±0.5 LUFS and true peak ≤ −1 dBTP. A/B against today's baby voice so the voice character doesn't change.
5. **Ken Burns benchmark:** (a) numpy/OpenCV sub-pixel warp piped to ffmpeg, (b) ffmpeg per-frame scale+crop, (c) zoompan on 2× upscale. Measure fps, CPU and visible shudder, then keep the winner.
6. **Visuals + effects:** bake stage, cached overlays, render pass, QSV encode with x264 fallback.
7. **Captions:** ASS generator with word highlight, hook and CTA. Visual check against your published style.
8. **End-to-end + tests:** a unit test per stage and one end-to-end test (2 short lines, 1 image, `fast` preset, ~10 s).
9. **Docs:** README rewrite (setup, run, config, architecture diagram, adding an effect) and the before/after table.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| QSV not usable (driver/build issue) | Automatic fallback to libx264 `veryfast`, measured both ways |
| libass Tamil rendering has glitches | Test in step 1. Fallback: pre-render caption images with Pillow + raqm, or use a different font |
| Coqui text cleaner changes characters, breaking char→duration mapping | Map against the cleaned text the model actually used. Fallback: split line time proportionally by character count |
| Word timings drift after pitch/pace processing | Pace is a pure time scale (same factor applied to timings). Verified by a test |
| Generated particles look "cheap" | Loop is configurable. You can drop in your own overlay (e.g. the ones you use in your editor) |
| Voice sounds different | Presets are kept unchanged. A/B check in step 4 |

## 8. New dependencies and costs

- **FFmpeg 9.0.2 full build** (gyan.dev, ≈100 MB zip, free, GPL): download needs your OK.
- **One Tamil OFL font** (Google Fonts, <1 MB, free): download needs your OK.
- **opencv-python-headless** (only if it wins the Ken Burns benchmark): pip install.
- No paid APIs, and no new AI models.
- Removals free ~4+ GB (SadTalker, its venv, GFPGAN) if you choose to delete them.

## 9. What I need from you

1. **Approve this plan** (or tell me what to change).
2. OK to `git init` this folder and work on a `redesign` branch?
3. OK to download FFmpeg 9.0.2 (gyan.dev) and a Tamil font (Google Fonts)?
4. Background music: keep `assets/murugan_baby.mp3` as the default track? Make sure you have the rights to it; YouTube Audio Library tracks are a free alternative.

---

## 10. Results (measured 2026-09-26, after implementation)

Same 8 lines, same image, same laptop. Both runs cold (nothing cached).

| | Before (`test.py --voice baby`) | After (`python -m shorts make`) |
|---|---|---|
| **Total time** | **2 h 8 min 33 s** (7,713 s) | **107.5 s** cold · **40.8 s** cached (≈72× / 189× faster) |
| Voice (load + synthesize) | ~69 s (two speakers; one unused) | 63.1 s cold (one speaker) · 0 s cached |
| Voice processing / audio | 1.5 s (pitch only: no EQ, loudness or music) | 9.1 s (pitch, pace, music, ducking, loudness) |
| Video | 2 h 5 min SadTalker + 1.4 s pad | 33.7 s render (motion 18.7, effects 5.8, colour convert 5.3, encoder wait 2.4) |
| Peak RAM | 4.7 GB | 2.1 GB cold (during voice model) · 0.37 GB cached |
| Output | 256×456, 0.45 MB, **needs manual editing** | **finished** 1080×1920 Short, 10 MB, 37.3 s, −14.0 LUFS / −1.0 dBTP |
| Manual editing | captions, effects, music, loudness, 1080p export | none |

Notes:
- Peak RAM missed my 1.5 GB estimate: PyTorch doesn't hand back all memory after the voice model loads.
- Ken Burns method chosen by measurement: 900 frames at 1080×1920 took 30 s wall / 123 s CPU with OpenCV bilinear (shudder 0.0029), vs 104 s / 146 s with visible shudder (0.0505) for a corrected ffmpeg `zoompan`. The commonly used zoompan recipe produced a **static** video. Pillow took over 30 min.
- Pause between lines is 930 ms to match the published pacing. The old code added a hidden 454 ms of silence after every sentence (Coqui `tts()`), then slowed everything by 1.2×.
- Two early runs stalled for ~20 minutes each. The event log shows Windows Modern Standby at exactly those times. The pipeline now asks Windows not to idle-sleep while it runs (`[run] keep_awake`).

### What I'd improve next
1. Run the voice model in a short-lived subprocess, so its ~1.7 GB is fully released before rendering (peak RAM ~1.3 GB).
2. Move motion to the Iris Xe GPU (OpenCL/Vulkan warp). It's the largest remaining render cost (~19 s).
3. Evaluate IndicF5 for a more natural voice, gated on a benchmark on this CPU.
4. Automatic caption placement that avoids faces (a face detector on each baked image, once).
