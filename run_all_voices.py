import subprocess
import os

BASE_DIR = r"C:\\bhakthishorts\\bhakti-shorts-automation\\Murugan"
SCRIPT_PATH = os.path.join(BASE_DIR, "murugan_voice_gen.py")

voices = ["baby", "young_male", "male"]

for voice in voices:
    print(f"--- Running for voice: {voice} ---")
    with open(f"{voice}.log", "w", encoding="utf-8") as f:
        subprocess.run(["python", SCRIPT_PATH, "--voice", voice], stdout=f, stderr=f)
    print(f"--- Finished voice: {voice} ---\n")