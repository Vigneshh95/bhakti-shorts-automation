#!/usr/bin/env python3
import os, subprocess, logging, argparse
from datetime import datetime
from pydub import AudioSegment
from TTS.utils.synthesizer import Synthesizer  # IndicTTS-style inference
import numpy as np
from scipy.io.wavfile import write as scipy_wav_write

# ====== PROJECT FOLDERS ======
BASE_DIR = r"C:\\bhakthishorts\\bhakti-shorts-automation\\Murugan"
ASSETS   = os.path.join(BASE_DIR, "assets")
OUTPUTS  = os.path.join(BASE_DIR, "output")
TEMP     = os.path.join(BASE_DIR, "temp")
os.makedirs(ASSETS, exist_ok=True)
os.makedirs(OUTPUTS, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)

# ====== TODAY'S OUTPUT FOLDER ======
today_str = datetime.now().strftime("%Y-%m-%d")
today_folder = os.path.join(OUTPUTS, today_str)
os.makedirs(today_folder, exist_ok=True)

# ====== FILE PATHS ======
RAW_WAV   = os.path.join(today_folder, f"murugan_tts_raw_{today_str}.wav")
MODULATED_WAV = os.path.join(today_folder, f"murugan_tts_modulated_{today_str}.wav")
FINAL_WAV = os.path.join(today_folder, f"murugan_voice_final_{today_str}.wav")
FINAL_MP3 = os.path.join(today_folder, f"murugan_voice_final_{today_str}.mp3")

REF_VOICE = os.path.join(ASSETS, "murugan_baby.mp3")  # reference voice (not used for cloning here)
BGM_PATH  = ""      # optional BGM

logging.basicConfig(level=logging.INFO, format="%(message)s", encoding='utf-8')

# ====== TAMIL LINES ======
LINES = [
    "அன்பே மிகப் பெரிய வலிமை. ஒரு சிறிய உதவும் பெரிய மகிழ்ச்சியை தரும்.",
    "நல்ல சிந்தனைகள் உன்னை உயர்த்தும், தீய சிந்தனைகள் உன்னை தாழ்த்தும்.",
    "இன்று சிறிய ஒரு நல்ல செயலை தொடங்கு. நாளை அது உன்னை உயர்த்தும்.",
    "நல்ல எண்ணங்கள் மற்றும் அன்புடன் வாழ்ந்தால், ஒளியில் நீ நடப்பாய்."
]

# ====== INDIC TTS SYNTHESIZER (FastPitch + HiFi-GAN) ======
# Make sure these files exist in the checkpoints folders:
FASTPITCH_CKPT = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "best_model.pth")
FASTPITCH_CFG  = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "config.json")
SPEAKERS_PTH   = os.path.join(BASE_DIR, "checkpoints", "fastpitch", "speakers.pth")  # optional but recommended
HIFIGAN_CKPT   = os.path.join(BASE_DIR, "checkpoints", "hifigan", "best_model.pth")
HIFIGAN_CFG    = os.path.join(BASE_DIR, "checkpoints", "hifigan", "config.json")

# Check if model files exist
def check_model_files():
    """Check if all required model files exist"""
    files_to_check = [FASTPITCH_CKPT, FASTPITCH_CFG, SPEAKERS_PTH, HIFIGAN_CKPT, HIFIGAN_CFG]
    missing_files = []
    
    for file_path in files_to_check:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        logging.error("❌ Missing model files:")
        for file_path in missing_files:
            logging.error(f"   - {file_path}")
        logging.error("\n📥 Please download the Tamil IndicTTS models from:")
        logging.error("   https://github.com/AI4Bharat/Indic-TTS")
        logging.error("\n📂 Required structure:")
        logging.error("   checkpoints/")
        logging.error("   ├── fastpitch/")
        logging.error("   │   ├── best_model.pth")
        logging.error("   │   ├── config.json")
        logging.error("   │   └── speakers.pth")
        logging.error("   └── hifigan/")
        logging.error("       ├── best_model.pth")
        logging.error("       └── config.json")
        return False
    
    logging.info("✅ All model files found!")
    return True

# Initialize Synthesizer
tts_synth = None
if check_model_files():
    try:
        tts_synth = Synthesizer(
            tts_checkpoint=FASTPITCH_CKPT,
            tts_config_path=FASTPITCH_CFG,
            tts_speakers_file=SPEAKERS_PTH,   # set None if not available
            tts_languages_file=None,
            vocoder_checkpoint=HIFIGAN_CKPT,
            vocoder_config=HIFIGAN_CFG,
            encoder_checkpoint="",
            encoder_config="",
            use_cuda=False  # set True if you have a working CUDA setup
        )
        logging.info("✅ IndicTTS synthesizer initialized successfully!")
    except Exception as e:
        logging.error(f"❌ Failed to initialize IndicTTS synthesizer: {e}")
        tts_synth = None
else:
    logging.error("❌ Cannot initialize synthesizer without model files")

def synth_line_to_wav(text, out_wav, speaker_name="female", sr=16000):
    """Synthesize a single Tamil line to WAV using IndicTTS Synthesizer."""
    if tts_synth is None:
        logging.error("❌ TTS synthesizer not initialized. Please check model files.")
        return False
        
    # logging.info(f"🔊 Synthesizing: {text}")
    try:
        audio = tts_synth.tts(
            text=text,
            speaker_name=speaker_name,
        )
        if isinstance(audio, list):
            audio = np.array(audio)
        
        if isinstance(audio, np.ndarray):
            audio_normalized = audio / np.max(np.abs(audio)) if np.max(np.abs(audio)) > 0 else audio
            audio_int16 = (audio_normalized * 32767).astype(np.int16)
            scipy_wav_write(out_wav, sr, audio_int16)
        else:
            logging.error(f"❌ Unexpected audio type: {type(audio)}")
            return False
        logging.info(f"✅ Synthesized: {out_wav}")
        return True
    except Exception as e:
        logging.error(f"❌ Error synthesizing '{text}': {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return False

def synth_lines_to_wav(lines, out_wav, silence_ms=380, speaker_name="female"):
    """Convert lines → stitched WAV with pauses."""
    if tts_synth is None:
        logging.error("❌ TTS synthesizer not initialized. Cannot synthesize lines.")
        return False
        
    parts = []
    for i, text in enumerate(lines):
        tmp = os.path.join(TEMP, f"line_{i}.wav")
        if synth_line_to_wav(text, tmp, speaker_name=speaker_name):
            parts.append(AudioSegment.from_file(tmp, format="wav"))
            if i < len(lines) - 1:
                parts.append(AudioSegment.silent(duration=silence_ms))
        else:
            logging.error(f"❌ Failed to synthesize line {i}: {text}")
            return False
            
    if parts:
        final = sum(parts[1:], parts[0]) if parts else AudioSegment.silent(0)
        final.export(out_wav, format="wav")
        logging.info(f"✅ Raw narration saved -> {out_wav}")
        return True
    else:
        logging.error("❌ No audio parts generated")
        return False

def ffmpeg_voice_modulate(in_wav, out_wav, voice_style="baby", normalize=True):
    """Apply various voice modulation effects based on style preset."""
    
    presets = {
        "baby": {
            "semitones": 7, "speed": 1.3, "reverb": "aecho=0.8:0.88:60:0.35",
            "description": "Childlike voice with higher pitch"
        },
        "young_male": {
            "semitones": -1, "speed": 0.88, "reverb": "aecho=0.6:0.65:130:0.4",
            "description": "Young divine Tamil male: slower, clear, mild depth"
        },
        "male": {
            "semitones": 0, "speed": 1.0, "reverb": "aecho=0.1:0.1:10:0.1",
            "description": "Normal male voice"
        },
    }
    
    if voice_style not in presets:
        logging.warning(f"⚠️  Unknown voice style '{voice_style}', using 'male'")
        voice_style = "male"
    
    preset = presets[voice_style]
    logging.info(f"🎭 Applying '{voice_style}' voice style: {preset['description']}")
    
    factor = 2 ** (preset["semitones"] / 12.0)
    atempo = preset["speed"] / factor
    
    filters = [
        f"asetrate=44100*{factor}",
        "aresample=44100", 
        f"atempo={atempo}",
        preset["reverb"]
    ]
    
    if normalize:
        filters.append("loudnorm=I=-14:LRA=7:TP=-1.5")
    
    af = ",".join(filters)
    
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", in_wav, "-af", af, out_wav]
    logging.info(f"🎛️  Applying FFmpeg filters: {af}")
    subprocess.check_call(cmd)
    logging.info(f"✅ Voice modulated ({voice_style}) saved -> {out_wav}")

def optional_mix_bgm(voice_path, out_path, bgm_path, bgm_db=-18):
    """Mix background music if available."""
    if not os.path.exists(bgm_path):
        logging.info("ℹ️  No BGM found; skipping.")
        AudioSegment.from_file(voice_path).export(out_path, format=out_path.split(".")[-1])
        return
    v = AudioSegment.from_file(voice_path)
    b = AudioSegment.from_file(bgm_path) + bgm_db
    b_loop = (b * (int(len(v)/len(b)) + 2))[:len(v)]
    mix = v.overlay(b_loop)
    mix.export(out_path, format=out_path.split(".")[-1])
    logging.info(f"🎵 Final with BGM -> {out_path}")

def wav_to_mp3(in_wav, out_mp3):
    """Convert WAV → MP3."""
    AudioSegment.from_file(in_wav, format="wav").export(out_mp3, format="mp3")
    logging.info(f"🎧 MP3 exported -> {out_mp3}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Murugan narration with different voice styles.")
    parser.add_argument("--voice", type=str, choices=["baby", "young_male", "male"], default="male",
                        help="Choose the voice style: baby, young_male, or male.")
    args = parser.parse_args()

    logging.info(f"🚀 Generating Murugan narration for {today_str} with '{args.voice}' voice...")
    
    if tts_synth is None:
        logging.error("❌ Cannot proceed without TTS synthesizer. Please check model files.")
        exit(1)

    speaker_name = "female" if args.voice == "baby" else "male"
    
    if synth_lines_to_wav(LINES, RAW_WAV, silence_ms=420, speaker_name=speaker_name):
        logging.info("✅ Tamil narration generated successfully!")
        
        ffmpeg_voice_modulate(RAW_WAV, MODULATED_WAV, voice_style=args.voice, normalize=True)
        
        optional_mix_bgm(MODULATED_WAV, FINAL_WAV, BGM_PATH, bgm_db=-20)
        
        wav_to_mp3(FINAL_WAV, FINAL_MP3)
        
        # try:
        #     for f in [RAW_WAV, MODULATED_WAV, FINAL_WAV]:
        #         if os.path.exists(f):
        #             os.remove(f)
        # except Exception as ce:
        #     logging.warning(f"⚠️  Cleanup warning: {ce}")

        logging.info("✅ Done. Single output file:")
        logging.info(f"   MP3 : {FINAL_MP3}")
    else:
        logging.error("❌ Failed to generate Tamil narration. Please check the logs above.")
        exit(1)