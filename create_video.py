import os
import subprocess
import logging
import argparse
from datetime import datetime
from moviepy.editor import VideoFileClip

# ====== PROJECT FOLDERS ======
BASE_DIR = r"C:\bhakthishorts\bhakti-shorts-automation\Murugan"
ASSETS   = os.path.join(BASE_DIR, "assets")
OUTPUTS  = os.path.join(BASE_DIR, "output")
WAV2LIP_DIR = os.path.join(BASE_DIR, "Wav2Lip")
TEMP       = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP, exist_ok=True)


# ====== TODAY'S FOLDER ======
today_str = datetime.now().strftime("%Y-%m-%d")
today_folder = os.path.join(OUTPUTS, today_str)

# ====== FILE PATHS ======
AUDIO_PATH = os.path.join(today_folder, f"murugan_voice_final_{today_str}.mp3")
VIDEO_PATH = os.path.join(today_folder, f"murugan_video_{today_str}.mp4")
WAV2LIP_CHECKPOINT = os.path.join(WAV2LIP_DIR, "checkpoints", "wav2lip_gan.pth")
WAV2LIP_INFERENCE_SCRIPT = os.path.join(WAV2LIP_DIR, "inference.py")

logging.basicConfig(level=logging.INFO, format="%(message)s")

def get_image_path(character):
    """Gets the image path for the given character."""
    image_map = {
        "baby": "baby.jpg",
        "young_male": "young_male.jpg",
        "male": "murugan.jpg"
    }
    image_file = image_map.get(character, "murugan.jpg")
    return os.path.join(ASSETS, image_file)

def create_video_with_lipsync(character):
    """
    Creates a lip-synced video using Wav2Lip.
    """
    image_path = get_image_path(character)

    if not os.path.exists(AUDIO_PATH):
        logging.error(f"Audio file not found: {AUDIO_PATH}")
        logging.error("Please run the voice generation script first.")
        return

    if not os.path.exists(image_path):
        logging.error(f"Image file not found: {image_path}")
        logging.error(f"Please make sure the image file for '{character}' exists in the 'assets' folder.")
        return

    if not os.path.exists(WAV2LIP_CHECKPOINT) or not os.path.exists(WAV2LIP_INFERENCE_SCRIPT):
        logging.error("Wav2Lip is not set up correctly.")
        logging.error(f"Please make sure the Wav2Lip directory exists at: {WAV2LIP_DIR}")
        logging.error("And that it contains the pre-trained model and inference script.")
        return

    cmd = [
        "python",
        WAV2LIP_INFERENCE_SCRIPT,
        "--checkpoint_path", WAV2LIP_CHECKPOINT,
        "--face", image_path,
        "--audio", AUDIO_PATH,
        "--outfile", VIDEO_PATH,
        "--pads", "0", "10", "0", "0"
    ]

    logging.info(f"Starting video generation with Wav2Lip for character: {character}...")
    logging.info(f"Command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Successfully created video: {VIDEO_PATH}")
    except subprocess.CalledProcessError as e:
        logging.error("Wav2Lip video generation failed.")
        logging.error(f"Return code: {e.returncode}")
        logging.error(f"Stderr: {e.stderr}")
        return
    except FileNotFoundError:
        logging.error("`python` command not found. Please ensure Python is installed and in your system's PATH.")
        return

    # Adjust video to 9:16 aspect ratio
    if os.path.exists(VIDEO_PATH):
        logging.info("✂️ Adjusting video to 9:16 aspect ratio for shorts...")
        original_clip = VideoFileClip(VIDEO_PATH)
        original_width, original_height = original_clip.size

        target_aspect_ratio = 9/16
        current_aspect_ratio = original_width / original_height

        if abs(current_aspect_ratio - target_aspect_ratio) > 0.01:
            target_width = int(original_height * target_aspect_ratio)

            if target_width <= original_width:
                x_center = original_width / 2
                cropped_clip = original_clip.crop(
                    x_center=x_center,
                    width=target_width
                )
                logging.info(f"  Cropped video width from {original_width} to {target_width} while maintaining height {original_height}.")
            else:
                target_height = int(original_width / target_aspect_ratio)
                y_center = original_height / 2
                cropped_clip = original_clip.crop(
                    y_center=y_center,
                    height=target_height
                )
                logging.info(f"  Cropped video height from {original_height} to {target_height} while maintaining width {original_width}.")

            temp_cropped_video_path = os.path.join(TEMP, f"cropped_{os.path.basename(VIDEO_PATH)}")
            cropped_clip.write_videofile(temp_cropped_video_path, codec="libx264", audio_codec="aac", fps=original_clip.fps)
            original_clip.close()
            cropped_clip.close()

            os.replace(temp_cropped_video_path, VIDEO_PATH)
            logging.info(f"✅ Video adjusted to 9:16 aspect ratio. New dimensions: {VideoFileClip(VIDEO_PATH).size[0]}x{VideoFileClip(VIDEO_PATH).size[1]}.")
        else:
            logging.info("☑️ Video already close to 9:16 aspect ratio. No adjustment needed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a lip-synced video with different characters.")
    parser.add_argument("--character", type=str, choices=["baby", "young_male", "male"], default="male",
                        help="Choose the character: baby, young_male, or male.")
    args = parser.parse_args()
    create_video_with_lipsync(args.character)