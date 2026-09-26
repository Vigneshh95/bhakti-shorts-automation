
import os
import subprocess
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAD_TALKER_DIR = os.path.join(BASE_DIR, 'SadTalker')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
DATE_STR = datetime.now().strftime('%Y-%m-%d')
TODAY_OUTPUT_DIR = os.path.join(OUTPUT_DIR, DATE_STR)

# Create directories if they don't exist
os.makedirs(TODAY_OUTPUT_DIR, exist_ok=True)

# --- Step 1: Generate Audio ---
def generate_audio():
    """
    Runs the voice generation script to create the audio file.
    """
    logging.info("--- Step 1: Generating Audio ---")
    voice_gen_script = os.path.join(BASE_DIR, 'murugan_voice_gen.py')
    audio_output_mp3 = os.path.join(TODAY_OUTPUT_DIR, f'murugan_voice_final_{DATE_STR}.mp3')


    command = [
        'python',
        voice_gen_script,
        '--voice', 'baby'
    ]

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', env=env)
        logging.info("Audio generation successful.")
        return audio_output_mp3
    except subprocess.CalledProcessError as e:
        logging.error(f"Audio generation failed: {e}")
        logging.error(f"Stderr: {e.stderr}")
        logging.error(f"Stdout: {e.stdout}")
        return None

# --- Step 2: Generate Video ---
def generate_video(audio_path):
    """
    Runs the SadTalker inference script to generate the video.
    """
    logging.info("--- Step 2: Generating Video ---")
    sadtalker_script = os.path.join(SAD_TALKER_DIR, 'inference.py')
    sadtalker_python = os.path.join(BASE_DIR, '.sadtalker_env', 'Scripts', 'python.exe')
    source_image = os.path.join(ASSETS_DIR, 'murugan.jpg')
    result_dir = os.path.join(BASE_DIR, 'results')

    command = [
        sadtalker_python,
        sadtalker_script,
        '--driven_audio', audio_path,
        '--source_image', source_image,
        '--result_dir', result_dir,
        '--enhancer', 'gfpgan',
        '--preprocess', 'full',
        '--still'
    ]

    try:
        subprocess.run(command, check=True, cwd=SAD_TALKER_DIR)
        logging.info("Video generation successful.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Video generation failed: {e}")
        logging.error(f"Stderr: {e.stderr}")
        logging.error(f"Stdout: {e.stdout}")


# --- Main Execution ---
if __name__ == '__main__':
    # Step 1: Generate audio
    generated_audio_path = generate_audio()

    # Step 2: Generate video if audio was created successfully
    if generated_audio_path:
        generate_video(generated_audio_path)
    else:
        logging.error("Could not proceed to video generation because audio generation failed.")
