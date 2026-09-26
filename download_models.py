#!/usr/bin/env python3
"""
Download script for IndicTTS Tamil models
Downloads FastPitch and HiFi-GAN models from AI4Bharat repository
"""

import os
import requests
import zipfile
from pathlib import Path

# Model URLs (these are the standard AI4Bharat IndicTTS Tamil model URLs)
MODEL_URLS = {
    "fastpitch": "https://github.com/AI4Bharat/Indic-TTS/releases/download/v1.0/tamil_fastpitch.zip",
    "hifigan": "https://github.com/AI4Bharat/Indic-TTS/releases/download/v1.0/tamil_hifigan.zip"
}

def download_file(url, filename):
    """Download a file from URL with progress bar"""
    print(f"📥 Downloading {filename}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0
    
    with open(filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    print(f"\r📥 Progress: {percent:.1f}%", end='', flush=True)
    
    print(f"\n✅ Downloaded {filename}")

def extract_zip(zip_path, extract_to):
    """Extract zip file to specified directory"""
    print(f"📦 Extracting {zip_path}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    print(f"✅ Extracted to {extract_to}")

def setup_models():
    """Download and setup Tamil TTS models"""
    print("🚀 Setting up IndicTTS Tamil models...")
    
    # Create directories
    fastpitch_dir = Path("checkpoints/fastpitch")
    hifigan_dir = Path("checkpoints/hifigan")
    fastpitch_dir.mkdir(parents=True, exist_ok=True)
    hifigan_dir.mkdir(parents=True, exist_ok=True)
    
    # Download FastPitch model
    fastpitch_zip = "tamil_fastpitch.zip"
    try:
        download_file(MODEL_URLS["fastpitch"], fastpitch_zip)
        extract_zip(fastpitch_zip, "temp_extract")
        
        # Move files to correct locations
        temp_fastpitch = Path("temp_extract")
        for file in temp_fastpitch.glob("**/*"):
            if file.is_file():
                if "fastpitch" in str(file).lower() or file.suffix in [".pth", ".json"]:
                    dest = fastpitch_dir / file.name
                    file.rename(dest)
                    print(f"📁 Moved {file.name} to fastpitch/")
        
        os.remove(fastpitch_zip)
        print("✅ FastPitch model setup complete")
        
    except Exception as e:
        print(f"❌ Error downloading FastPitch: {e}")
        print("💡 You may need to download manually from: https://github.com/AI4Bharat/Indic-TTS")
    
    # Download HiFi-GAN model
    hifigan_zip = "tamil_hifigan.zip"
    try:
        download_file(MODEL_URLS["hifigan"], hifigan_zip)
        extract_zip(hifigan_zip, "temp_extract_hifi")
        
        # Move files to correct locations
        temp_hifigan = Path("temp_extract_hifi")
        for file in temp_hifigan.glob("**/*"):
            if file.is_file():
                if "hifigan" in str(file).lower() or file.suffix in [".pth", ".json"]:
                    dest = hifigan_dir / file.name
                    file.rename(dest)
                    print(f"📁 Moved {file.name} to hifigan/")
        
        os.remove(hifigan_zip)
        print("✅ HiFi-GAN model setup complete")
        
    except Exception as e:
        print(f"❌ Error downloading HiFi-GAN: {e}")
        print("💡 You may need to download manually from: https://github.com/AI4Bharat/Indic-TTS")
    
    # Clean up temp directories
    import shutil
    for temp_dir in ["temp_extract", "temp_extract_hifi"]:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
    
    print("\n🎉 Model setup complete!")
    print("📂 Check your checkpoints/ directory:")
    print("   checkpoints/fastpitch/")
    print("   checkpoints/hifigan/")

if __name__ == "__main__":
    setup_models()








