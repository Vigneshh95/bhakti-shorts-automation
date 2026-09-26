import os
import subprocess
import logging
from datetime import datetime

# ---------- CONFIG ----------
BASE_DIR = r"C:\bhakthishorts\bhakti-shorts-automation\Murugan"
OUTPUTS  = os.path.join(BASE_DIR, "output")
today = datetime.now().strftime("%Y-%m-%d")
OUT_DIR = os.path.join(OUTPUTS, today, "speaker_tests")
os.makedirs(OUT_DIR, exist_ok=True)

# Input file from the previous run
INPUT_WAV = os.path.join(OUT_DIR, "raw_male.wav")

# Output file
OUTPUT_WAV = os.path.join(OUT_DIR, f"murugan_final_{today}.wav")
OUTPUT_MP3 = os.path.join(OUT_DIR, f"murugan_final_{today}.mp3")

# ffmpeg parameters
SLOWDOWN_TEMPO = 0.995
PITCH_SHIFT_RATIO = 1.05  # 5% pitch increase
REVERB_PARAMS = "0.8:0.9:1000:0.15" # in_gain:out_gain:delays:decays

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def process_audio():
    """
    Applies tempo, pitch, and reverb to the input audio file using ffmpeg.
    """
    if not os.path.exists(INPUT_WAV):
        logging.error(f"Input file not found: {INPUT_WAV}")
        logging.error("Please run the previous script to generate 'raw_male.wav' first.")
        return

    # Construct the ffmpeg command
    atempo_filter = f"atempo={SLOWDOWN_TEMPO}"
    pitch_filter = f"asetrate=44100*{PITCH_SHIFT_RATIO},atempo={1/PITCH_SHIFT_RATIO}"
    reverb_filter = f"aecho={REVERB_PARAMS}"

    af_filters = [
        atempo_filter,
        pitch_filter,
        reverb_filter
    ]

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", INPUT_WAV,
        "-af", ",".join(af_filters),
        OUTPUT_WAV
    ]

    logging.info(f"Running ffmpeg command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Successfully created processed WAV file: {OUTPUT_WAV}")

        # Convert to MP3
        from pydub import AudioSegment
        AudioSegment.from_file(OUTPUT_WAV).export(OUTPUT_MP3, format="mp3", bitrate="192k")
        logging.info(f"Successfully created final MP3 file: {OUTPUT_MP3}")

    except subprocess.CalledProcessError as e:
        logging.error("ffmpeg processing failed.")
        logging.error(f"Return code: {e.returncode}")
        logging.error(f"Stderr: {e.stderr}")
    except FileNotFoundError:
        logging.error("`ffmpeg` not found. Please ensure it is installed and in your system's PATH.")


if __name__ == "__main__":
    process_audio()