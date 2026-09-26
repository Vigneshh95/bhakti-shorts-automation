#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'TTS')))
"""
murugan_rubberband_pipeline_v2.py
Updated pipeline to produce a "young male divine Murugan" voice.

Behavior:
 - Attempt formant-preserving rubberband pitch+tempo (preferred).
 - If rubberband unavailable, use pyworld to scale F0 and slightly warp formants.
 - EQ, compress, two-pass loudness normalization, optional BGM and reverb.
"""

import os
import subprocess
import logging
import shutil
import re
import atexit
from datetime import datetime
from pydub import AudioSegment
from TTS.utils.synthesizer import Synthesizer
import numpy as np
from scipy.io.wavfile import write as scipy_wav_write
import torch
import sys
from contextlib import contextmanager
import argparse

# optional (WORLD fallback)
try:
    import pyworld as pw
    import soundfile as sf
    WORLD_AVAILABLE = True
except Exception:
    WORLD_AVAILABLE = False

# ---------- CONFIG ----------
BASE_DIR = r"C:\bhakthishorts\bhakti-shorts-automation\Murugan"
ASSETS   = os.path.join(BASE_DIR, "assets")
OUTPUTS  = os.path.join(BASE_DIR, "output")
TEMP     = os.path.join(BASE_DIR, "temp")
os.makedirs(ASSETS, exist_ok=True)
os.makedirs(OUTPUTS, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)

today = datetime.now().strftime("%Y-%m-%d")
OUT_DIR = os.path.join(OUTPUTS, today, "speaker_tests")
os.makedirs(OUT_DIR, exist_ok=True)

# TTS checkpoints (update paths if needed)
FASTPITCH_CKPT = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "best_model.pth")
FASTPITCH_CFG  = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "config.json")
SPEAKERS_PTH   = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "speakers.pth")
HIFIGAN_CKPT   = os.path.join(BASE_DIR, "checkpoints", "hifigan", "best_model.pth")
HIFIGAN_CFG    = os.path.join(BASE_DIR, "checkpoints", "hifigan", "config.json")

# Voice lines (Tamil)
LINES = [
# Introduction & Setting the Context (1-3)
    "முருகன் சொல்வது.",
    "இன்று உனக்கு நான் அருளும் வாக்கு இது.",
    "பொறுமை காப்பவனே, என் பேரருளைப் பெறுவான்.",
    "சோதனைகள் உன்னை வீழ்த்த அல்ல, செதுக்கவே வருகின்றன.",
    "காலம் கனியும் வரை அமைதியுடன் காத்திருக்கப் பழகு.",
    "விடாமுயற்சி என்னும் வேல் உன்னிடம் இருந்தால், வெற்றி நிச்சயம்.",
    "விரைவாகக் கிடைப்பது நிலைக்காது; நிலைப்பது எளிதில் கிடைக்காது.",
    "கலங்காதே. உனக்கான காலம் மிக விரைவில் வரும்.",
]


# Rubber Band parameters (conservative)
RB_SEMITONES = 4.0   # raise pitch by +4.0 semitones
RB_TEMPO = 1.25      # speed up by 25%

# --- IMPORTANT: CONFIGURE YOUR ASSETS ---
# The user can update the image and bgm in the assets folder.
# The script will pick the first .jpg or .png as the image, and the first .mp3 or .wav as the BGM.
def find_asset(extensions):
    for ext in extensions:
        for file in os.listdir(ASSETS):
            if file.lower().endswith(ext):
                return os.path.join(ASSETS, file)
    return None

SOURCE_IMAGE_PATH = os.path.join(ASSETS, 'murugan.png')
BGM_PATH = os.path.join(ASSETS, 'murugan_baby.mp3')

TARGET_LUFS = -14.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------- tiny tmp cleanup ----------
TMP_TO_REMOVE = []
def _register_tmp(path):
    TMP_TO_REMOVE.append(path)

@atexit.register
def _cleanup_tmp():
    for p in TMP_TO_REMOVE:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

# ---------- helpers ----------
@contextmanager
def suppress_stdout_stderr():
    """A context manager that redirects stdout and stderr to devnull"""
    with open(os.devnull, 'w', encoding='utf-8') as fnull:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = fnull, fnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


def check_models_exist():
    files = [FASTPITCH_CKPT, FASTPITCH_CFG, SPEAKERS_PTH, HIFIGAN_CKPT, HIFIGAN_CFG]
    missing = [p for p in files if not os.path.exists(p)]
    if missing:
        logging.error("❌ Missing checkpoint files:")
        for p in missing:
            logging.error("   - " + p)
        return False
    return True

def list_speakers():
    logging.info("speakers.pth exists? %s", os.path.exists(SPEAKERS_PTH))
    try:
        data = torch.load(SPEAKERS_PTH, map_location="cpu")
        if isinstance(data, dict):
            keys = list(data.keys())
            logging.info("speakers.pth top-level keys: %s", keys[:20])
            return keys
        elif isinstance(data, (list, tuple)):
            logging.info("speakers.pth is list/tuple, len=%d", len(data))
            return data
        else:
            logging.info("speakers.pth loaded with type %s", type(data))
            return []
    except Exception as e:
        logging.warning("Could not list speakers: %s", e)
        return []

def init_synth():
    return Synthesizer(
        tts_checkpoint=FASTPITCH_CKPT,
        tts_config_path=FASTPITCH_CFG,
        tts_speakers_file=SPEAKERS_PTH,
        tts_languages_file=None,
        vocoder_checkpoint=HIFIGAN_CKPT,
        vocoder_config=HIFIGAN_CFG,
        encoder_checkpoint="",
        encoder_config="",
        use_cuda=False
    )

def synth_text_to_wav(synth, text, out_wav, speaker_name="male"):
    logging.info("🔊 Synthesizing as '%s' -> %s", speaker_name, out_wav)
    with suppress_stdout_stderr():
        audio = synth.tts(text=text, speaker_name=speaker_name)
    arr = np.array(audio, dtype=np.float32)
    # normalize
    arr = arr / (np.max(np.abs(arr)) + 1e-9)
    # try to fetch synth sample rate if available; fallback to 22050 or 16000
    sr = getattr(synth, "sample_rate", None) or getattr(synth, "config", {}).get("audio", {}).get("sample_rate", None)
    if sr is None:
        sr = 22050  # many TTS vocoders use 22050
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    # write as 16-bit
    scipy_wav_write(out_wav, int(sr), (arr * 32767).astype('int16'))

def stitch_lines_raw(synth, lines, out_wav, speaker_name="male", silence_ms=320):
    parts = []
    for i, line in enumerate(lines):
        tmp = os.path.join(TEMP, f"line_{speaker_name}_{i}_raw.wav")
        synth_text_to_wav(synth, line, tmp, speaker_name=speaker_name)
        _register_tmp(tmp)
        parts.append(AudioSegment.from_file(tmp, format="wav"))
        if i < len(lines)-1:
            parts.append(AudioSegment.silent(duration=silence_ms))
    if not parts:
        raise ValueError("No lines provided to stitch_lines_raw()")
    final = parts[0]
    for p in parts[1:]:
        final = final + p
    final.export(out_wav, format="wav")
    logging.info("✅ Stitched raw WAV written -> %s", out_wav)

def find_rubberband():
    rb = shutil.which("rubberband")
    if rb:
        return rb
    candidate = r"C:\tools\rubberband\rubberband.exe"
    if os.path.exists(candidate):
        return candidate
    return None

def run_rubberband(rubberband_exe, in_wav, out_wav, semitones=2.0, tempo=1.05):
    cmd = [rubberband_exe, "-p", str(semitones), "-t", str(tempo), in_wav, out_wav]
    logging.info("🔁 Running rubberband: %s", " ".join(cmd))
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if res.stdout:
            logging.debug(res.stdout)
        if res.stderr:
            logging.debug(res.stderr)
        logging.info("✅ rubberband output -> %s", out_wav)
    except subprocess.CalledProcessError as e:
        logging.error("rubberband failed: returncode=%s stderr=%s", e.returncode, e.stderr)
        raise

def build_atempo(speed):
    parts = []
    x = float(speed)
    while x > 2.0:
        parts.append("atempo=2.0")
        x /= 2.0
    while x < 0.5:
        parts.append("atempo=0.5")
        x /= 0.5
    parts.append(f"atempo={x:.4f}")
    return ",".join(parts)

def two_pass_loudnorm(in_wav, out_wav, target_lufs=TARGET_LUFS):
    measure_cmd = [
        "ffmpeg","-y","-hide_banner","-loglevel","error",
        "-i", in_wav,
        "-af", f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5:print_format=summary",
        "-f", "null", "-"
    ]
    try:
        out = subprocess.check_output(measure_cmd, stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as e:
        out = e.output.decode() if e.output else ""
    # robust regex extraction
    def _rx(k):
        m = re.search(rf"{k}\s*:\s*([-\d\.]+)", out)
        return m.group(1) if m else None

    mi = _rx("input_i") or _rx("Input Integrated")
    mlra = _rx("input_lra")
    mtp = _rx("input_tp")
    mth = _rx("input_thresh") or _rx("input_threshold")

    if not all([mi, mlra, mtp, mth]):
        logging.warning("Could not parse measured loudness from ffmpeg output; falling back to single-pass loudnorm.")
        cmd = ["ffmpeg","-y","-hide_banner","-loglevel","error","-i", in_wav,
               "-af", f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5", out_wav]
        subprocess.check_call(cmd)
        return

    apply_af = (
        f"loudnorm=I={target_lufs}:LRA=7:TP=-1.5:"
        f"measured_I={mi}:measured_LRA={mlra}:measured_TP={mtp}:measured_thresh={mth}"
    )
    cmd2 = ["ffmpeg","-y","-hide_banner","-loglevel","error","-i", in_wav, "-af", apply_af, out_wav]
    subprocess.check_call(cmd2)

def eq_and_compress(in_wav, out_wav, eq_gain=1.8, speed=1.0):
    atempo = build_atempo(speed)
    af = ",".join([
        "aresample=44100",
        "highpass=f=80",
        "anlmdn",
        atempo,
        f"equalizer=f=4000:t=q:w=0.5:g={eq_gain}",
        "acompressor=threshold=-18dB:ratio=4:attack=5:release=200:makeup=8"
    ])
    cmd = ["ffmpeg","-y","-hide_banner","-loglevel","error","-i", in_wav, "-af", af, out_wav]
    subprocess.check_call(cmd)

def optional_mix_bgm(voice_wav, out_wav, bgm_path, bgm_db=-15):
    if not bgm_path or not os.path.exists(bgm_path):
        logging.warning("BGM file not found, skipping background music.")
        AudioSegment.from_file(voice_wav).export(out_wav, format="wav")
        return
    try:
        cmd = [
            "ffmpeg","-y","-hide_banner","-loglevel","error",
            "-i", voice_wav, "-i", bgm_path,
            "-filter_complex",
            f"[1:a]aloop=loop=-1:size=2e+09,volume={bgm_db}dB[bg];[0:a][bg]sidechaincompress=threshold=-30dB:ratio=6:attack=5:release=200:makeup=8[out]",
            "-map","[out]", out_wav
        ]
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        v = AudioSegment.from_file(voice_wav)
        b = AudioSegment.from_file(bgm_path) + bgm_db
        b_loop = (b * (int(len(v)/len(b)) + 2))[:len(v)]
        mix = v.overlay(b_loop)
        mix.export(out_wav, format="wav")

def wav_to_mp3(in_wav, out_mp3, bitrate="192k"):
    AudioSegment.from_file(in_wav, format="wav").export(out_mp3, format="mp3", bitrate=bitrate)

# ---------- WORLD fallback function ----------
def world_pitch_formant_shift(in_wav, out_wav, semitones=2.0, formant_warp=1.03):
    """
    Use pyworld to scale F0 (pitch) and slightly warp the spectral envelope (formants).
    - semitones: +ve raises pitch
    - formant_warp: >1 shifts formants upward slightly (youthful/brighter)
    """
    if not WORLD_AVAILABLE:
        raise RuntimeError("pyworld or soundfile not available for WORLD processing")

    x, sr = sf.read(in_wav)                     # float64 array
    if x.ndim > 1:
        x = x.mean(axis=1)
    # harvest F0
    _f0, t = pw.harvest(x.astype(np.float64), sr)
    sp = pw.cheaptrick(x.astype(np.float64), _f0, t, sr)  # (frames, fftlen)
    ap = pw.d4c(x.astype(np.float64), _f0, t, sr)

    # scale F0
    ratio = 2.0 ** (semitones / 12.0)
    f0_new = _f0 * ratio

    # warp spectral envelope (simple bin resample): shift formant positions upward by factor
    # sp shape: (frames, fftlen)
    frames, fftlen = sp.shape
    # we will remap freq bins using interpolation
    orig_idx = np.arange(fftlen)
    # new index mapping: map each target bin to source bin by dividing by warp factor
    mapped = orig_idx / formant_warp
    # clamp
    mapped[mapped < 0] = 0
    mapped[mapped > fftlen - 1] = fftlen - 1

    sp_warped = np.zeros_like(sp)
    for i in range(frames):
        sp_warped[i, :] = np.interp(orig_idx, mapped, sp[i, :])

    # synthesize
    y = pw.synthesize(f0_new, sp_warped, ap, sr)
    # write
    sf.write(out_wav, y.astype(np.float32), sr)
    logging.info("✅ WORLD resynthesis written -> %s", out_wav)

# ---------- reverb pass (ffmpeg aecho) ----------
YOUNG_MALE_PRESET = {
    "semitones": 4.0,
    "tempo": 1.20,
    "formant_warp": 1.03,
    "eq_gain": 2.5,
    "reverb": False,
    "reverb_aecho": "0.8:0.88:1000:0.2"
}

BABY_PRESET = {
    "semitones": 4.0,
    "tempo": 1.20,
    "formant_warp": 1.12,
    "eq_gain": 2.0,
    "reverb": False,
    "reverb_aecho": "0.8:0.88:1000:0.2"
}

MALE_PRESET = {
    "semitones": 0,
    "tempo": 1.0,
    "formant_warp": 1.0,
    "eq_gain": 0,
    "reverb": False,
    "reverb_aecho": "0.1:0.1:10:0.1"
}

def add_reverb_ffmpeg(in_wav, out_wav, aecho_params):
    """
    Adds a gentle reverb using ffmpeg's aecho. Params are 'in_gain:out_gain:delays:decays'
    Example default: '0.8:0.9:1000:0.15'
    """
    cmd = ["ffmpeg","-y","-hide_banner","-loglevel","error","-i", in_wav,
           "-af", f"aecho={aecho_params}", out_wav]
    subprocess.check_call(cmd)
    logging.info("✅ Reverb applied -> %s", out_wav)

def run_sadtalker(audio_path, image_path, result_dir):
    """
    Runs SadTalker inference to generate a video from an audio file and an image.
    """
    if not image_path or not os.path.exists(image_path):
        logging.error("❌ Source image not found, cannot run SadTalker.")
        return None

    sadtalker_dir = os.path.join(BASE_DIR, "SadTalker")
    sadtalker_script = os.path.join(sadtalker_dir, "inference.py")
    python_executable = os.path.join(BASE_DIR, ".sadtalker_env", "Scripts", "python.exe")
    
    # Ensure result_dir exists
    os.makedirs(result_dir, exist_ok=True)

    cmd = [
        python_executable, sadtalker_script,
        "--driven_audio", audio_path,
        "--source_image", image_path,
        "--result_dir", result_dir,
        "--cpu",
        "--preprocess", "full",
        "--size", "256",
        "--expression_scale", "1.0",
        "--still"
    ]
    logging.info("🎬 Running SadTalker: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, cwd=sadtalker_dir)
        logging.info("✅ SadTalker video generated successfully!")
        # Find the generated video file
        for file in os.listdir(result_dir):
            if file.endswith('.mp4'):
                return os.path.join(result_dir, file)
    except subprocess.CalledProcessError as e:
        logging.error("❌ SadTalker failed: %s", e)
    return None

def pad_video_to_9_16(in_video, out_video):
    """Pads a video to a 9:16 aspect ratio."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", in_video,
        "-vf", "scale=w=256:h=256,pad=w=256:h=456:x=0:y=100:color=black",
        out_video
    ]
    logging.info("🎬 Padding video to 9:16 aspect ratio: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        logging.info("✅ Video padded successfully!")
    except subprocess.CalledProcessError as e:
        logging.error("❌ Failed to pad video: %s", e)



# ---------- pipeline ----------
def run_pipeline_preset(preset, voice_name, source_voice="male"):
    # Check if raw files exist, if not, generate them
    raw_male = os.path.join(OUT_DIR, "raw_male.wav")
    raw_female = os.path.join(OUT_DIR, "raw_female.wav")
    if not os.path.exists(raw_male) or not os.path.exists(raw_female):
        if not check_models_exist():
            logging.error("Missing models — cannot proceed.")
            return None
        synth = init_synth()
        stitch_lines_raw(synth, LINES, raw_male, speaker_name="male")
        stitch_lines_raw(synth, LINES, raw_female, speaker_name="female")
        logging.info("Wrote raw_male.wav and raw_female.wav into %s", OUT_DIR)

    source_file = os.path.join(OUT_DIR, f"raw_{source_voice}.wav")

    rb = find_rubberband()
    final_mp3 = None

    if rb:
        logging.info(f"🔎 Found rubberband at: %s — using it for {voice_name} preset", rb)
        male_rb = os.path.join(OUT_DIR, f"{voice_name}_rb_{today}.wav")
        try:
            run_rubberband(rb, source_file, male_rb, semitones=preset["semitones"], tempo=preset["tempo"])

            if voice_name == "baby":
                logging.info(f"✅ Using raw rubberband output for baby voice: %s", male_rb)
                return male_rb
            
            step1 = os.path.join(OUT_DIR, f"{voice_name}_rb_eq_{today}.wav")
            eq_and_compress(male_rb, step1, eq_gain=preset["eq_gain"], speed=1.0)
            reverb_out = os.path.join(OUT_DIR, f"{voice_name}_rb_reverb_{today}.wav")
            if preset["reverb"]:
                add_reverb_ffmpeg(step1, reverb_out, aecho_params=preset["reverb_aecho"])
            else:
                shutil.copy(step1, reverb_out)
            loud = os.path.join(OUT_DIR, f"{voice_name}_rb_loud_{today}.wav")
            two_pass_loudnorm(reverb_out, loud, target_lufs=TARGET_LUFS)
            final_wav = os.path.join(OUT_DIR, f"murugan_{voice_name}_{today}.wav")
            optional_mix_bgm(loud, final_wav, bgm_path=BGM_PATH, bgm_db=-15)
            # final_mp3 = os.path.join(OUT_DIR, f"murugan_{voice_name}_{today}.mp3")
            # wav_to_mp3(final_wav, final_mp3)
            logging.info(f"✅ Final {voice_name} (rubberband) wav: %s", final_wav)
            return final_wav
        except Exception as e:
            logging.warning(f"⚠ rubberband pipeline failed for {voice_name}: %s — trying WORLD fallback if available", e)

    if WORLD_AVAILABLE:
        try:
            world_out = os.path.join(OUT_DIR, f"{voice_name}_world_{today}.wav")
            world_pitch_formant_shift(source_file, world_out,
                                      semitones=preset["semitones"],
                                      formant_warp=preset["formant_warp"])
            step1 = os.path.join(OUT_DIR, f"{voice_name}_world_eq_{today}.wav")
            eq_and_compress(world_out, step1, eq_gain=preset["eq_gain"], speed=1.0)
            reverb_out = os.path.join(OUT_DIR, f"{voice_name}_world_reverb_{today}.wav")
            if preset["reverb"]:
                add_reverb_ffmpeg(step1, reverb_out, aecho_params=preset["reverb_aecho"])
            else:
                shutil.copy(step1, reverb_out)
            loud = os.path.join(OUT_DIR, f"{voice_name}_world_loud_{today}.wav")
            two_pass_loudnorm(reverb_out, loud, target_lufs=TARGET_LUFS)
            final_wav = os.path.join(OUT_DIR, f"murugan_{voice_name}_world_{today}.wav")
            optional_mix_bgm(loud, final_wav, bgm_path=BGM_PATH, bgm_db=-15)
            # final_mp3 = os.path.join(OUT_DIR, f"murugan_{voice_name}_world_{today}.mp3")
            # wav_to_mp3(final_wav, final_mp3)
            logging.info(f"✅ Final {voice_name} (WORLD) wav: %s", final_wav)
            return final_wav
        except Exception as e:
            logging.error(f"❌ WORLD fallback failed for {voice_name}: %s", e)

    try:
        logging.info(f"Using female fallback tuning to approximate {voice_name}.")
        step_f = os.path.join(OUT_DIR, f"{voice_name}_female_step_{today}.wav")
        eq_and_compress(raw_female, step_f, eq_gain=preset["eq_gain"], speed=preset["tempo"])
        if preset["reverb"]:
            reverb_f = os.path.join(OUT_DIR, f"{voice_name}_female_reverb_{today}.wav")
            add_reverb_ffmpeg(step_f, reverb_f, aecho_params=preset["reverb_aecho"])
        else:
            reverb_f = step_f
        loud_f = os.path.join(OUT_DIR, f"{voice_name}_female_loud_{today}.wav")
        two_pass_loudnorm(reverb_f, loud_f, target_lufs=TARGET_LUFS)
        final_f = os.path.join(OUT_DIR, f"murugan_fallback_{voice_name}_{today}.wav")
        optional_mix_bgm(loud_f, final_f, bgm_path=BGM_PATH, bgm_db=-15)
        final_mp3_f = os.path.join(OUT_DIR, f"murugan_fallback_{voice_name}_{today}.mp3")
        wav_to_mp3(final_f, final_mp3_f)
        logging.info(f"✅ Fallback {voice_name} mp3: %s", final_mp3_f)
        return final_mp3_f
    except Exception as e:
        logging.error(f"❌ Fallback pipeline failed for {voice_name}: %s", e)
    return None

# ---------- run ----------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Murugan narration with different voice styles and create a talking head video.")
    parser.add_argument("--voice", type=str, choices=["baby", "young_male", "male", "all"], default="all",
                        help="Choose the voice style: baby, young_male, male, or all.")
    args = parser.parse_args()

    if not SOURCE_IMAGE_PATH:
        logging.error("Could not find a .jpg or .png file in the assets folder.")
    if not BGM_PATH:
        logging.warning("Could not find a .mp3 or .wav file in the assets folder. Continuing without BGM.")

    if args.voice == "all" or args.voice == "young_male":
        # Generate young male voice and video
        young_male_audio = run_pipeline_preset(YOUNG_MALE_PRESET, "young_male", source_voice="male")
        if young_male_audio:
            video_path = run_sadtalker(young_male_audio, SOURCE_IMAGE_PATH, os.path.join(OUT_DIR, "young_male_video"))
            if video_path:
                padded_video_path = os.path.join(OUT_DIR, f"murugan_young_male_{today}_9x16.mp4")
                pad_video_to_9_16(video_path, padded_video_path)

    if args.voice == "all" or args.voice == "baby":
        # Generate baby voice and video
        baby_audio = run_pipeline_preset(BABY_PRESET, "baby", source_voice="female")
        if baby_audio:
            video_path = run_sadtalker(baby_audio, SOURCE_IMAGE_PATH, os.path.join(OUT_DIR, "baby_video"))
            if video_path:
                padded_video_path = os.path.join(OUT_DIR, f"murugan_baby_{today}_9x16.mp4")
                pad_video_to_9_16(video_path, padded_video_path)

    if args.voice == "all" or args.voice == "male":
        # Generate male voice and video
        male_audio = run_pipeline_preset(MALE_PRESET, "male", source_voice="male")
        if male_audio:
            video_path = run_sadtalker(male_audio, SOURCE_IMAGE_PATH, os.path.join(OUT_DIR, "male_video"))
            if video_path:
                padded_video_path = os.path.join(OUT_DIR, f"murugan_male_{today}_9x16.mp4")
                pad_video_to_9_16(video_path, padded_video_path)

    logging.info("Done. Check %s for outputs.", OUT_DIR)