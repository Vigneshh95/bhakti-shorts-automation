# Deivathin Kural Shorts: Sri Mahaperiyava series (plan)

A second daily series on the same one-click autopilot. Each Short retells, in simple spoken Tamil,
the essence of one chapter of *Deivathin Kural* (Sri Chandrasekharendra Saraswathi Mahaswamigal's
discourses, compiled by Ra. Ganapathy). It is narrated by a voice modelled on a sample the user
provides, over his photo with lip-sync. The Murugan series and the manual workflow are unchanged.

Decisions (user, 2026-09-30):

| Topic | Choice |
|---|---|
| Face | lip-sync like Murugan (SadTalker on Kaggle) |
| Voice | modelled on the user's sample (IndicF5 on Kaggle), and labelled as an AI voice |
| Upload | same channel (BrahmaNadagam), own playlist "தெய்வத்தின் குரல்" |
| Text | kamakoti.org (the Kanchi Math's own site) |

## Design

**One autopilot, two series.** `autopilot.toml` stays the Murugan series. `periyava.toml` is the new series, with its own settings:
- pictures (`periyava_images/`)
- history
- spare scripts
- output (`Final/periyava/`)
- publish time
- playlist
- prompts
- video look

Commands:
- `python -m autopilot run --series periyava`
- `periyava_short.bat` (make and upload)
- `periyava_preview.bat` (make only)

The code has no series-specific branches; everything that differs lives in the series file.

**Grounded content, so nothing is invented.**
1. `python -m autopilot source` collects the Tamil chapters of all 7 parts from kamakoti.org once into
   `sources/deivathin_kural/chapters.jsonl`: part, number, title, URL and text. It crawls politely, about one page a second, and resumes where it stopped.
2. Each chapter is judged once for daily-Short suitability: a practical, universal message a
   layperson can live by. Chapters on caste/varna duties, detailed ritual rules, polemics or
   pure philosophy that can't be put simply are left out. The verdicts are cached in the same folder.
3. Every day the planner takes the next unused suitable chapter, spread across the parts.
4. The writer gets the chapter's full text. It writes 6–9 short, simple Tamil lines in his gentle
   teaching voice ("நாம்", homely examples) that carry only that chapter's ideas. The last line is a
   blessing. No quotation is attributed unless it is in the chapter.
5. A separate reviewer compares the script with the chapter and rejects anything the chapter
   doesn't say, anything that is poor Tamil, and anything that isn't respectful.
6. The description credits the source, for example: தெய்வத்தின் குரல், பகுதி 1 — "அம்மா", kamakoti.org.

**Voice (Kaggle, free GPU).**
1. IndicF5 (AI4Bharat, MIT licence, supports Tamil) speaks each line in the reference voice. The reference is
   `voices/periyava_ref.wav`, 10–20 s, with its exact words in `voices/periyava_ref.txt`.
2. Word timings for the captions come from a forced aligner (torchaudio MMS) in the same Kaggle run.
3. Lines are cached like today's voice, so a re-run never repeats them.
4. On the laptop: a slightly slower pace, warmth, and a soft temple-hall echo. Under the voice, a quiet
   tanpura drone synthesised in code (no music licence needed), ducked automatically.
5. If IndicF5 is unavailable, the run stops with a clear message. It does not fall back to a
   different-sounding voice.

**Face.** The existing Kaggle SadTalker stage, with the voice as driving audio (about 10 min).

**Look.**
- warm saffron grade and soft glow
- cream captions with saffron key words
- the hook title "தெய்வத்தின் குரல்"
- an outro card with "ஜய ஜய சங்கர" and the source chapter
- a small "AI குரல்" label
- the channel watermark

**Upload.** The same channel and sign-in. Scheduled 06:30 IST, when the audience starts the day, with its own playlist.
The metadata is
- a Tamil-first title, e.g. "மகா பெரியவா அருள்வாக்கு | Deivathin Kural — Mother's Love";
- a description with the chapter credit and an honest note that this is an AI-voiced retelling;
- tags covering Mahaperiyava, Kanchi, Deivathin Kural and today's theme.

The AI-content flag is set, and uploads are limited to one per day for this series.

## Needed from the user
1. Photos of Mahaperiyava in `periyava_images/`: clear face, front-facing works best for lip-sync.
2. A clean 10–20 s voice sample (just his voice, no music) as `voices/periyava_ref.wav`. Claude
   transcribes it; you check the transcript.
3. A free Hugging Face account. Accept the IndicF5 terms at huggingface.co/ai4bharat/IndicF5, create a
   read token, and add it as a Kaggle secret named `HF_TOKEN` on the notebook `periyava-voice`.
   This keeps the token out of the code.
