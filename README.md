# Murugan Voice Generation - Tamil TTS Setup

This project generates Tamil voice narration using IndicTTS models with baby voice effects and background music mixing.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
# Activate virtual environment
.\.venv\Scripts\activate

# Dependencies are already installed:
# - PyTorch (CPU version)
# - TTS library
# - Audio processing libraries (scipy, pydub, librosa)
```

### 2. Download Tamil IndicTTS Models

**⚠️ IMPORTANT: You need to download the actual Tamil model files from AI4Bharat**

#### Option A: Manual Download
1. Visit: https://github.com/AI4Bharat/Indic-TTS
2. Download Tamil FastPitch and HiFi-GAN models
3. Extract and place files in the correct structure:

```
checkpoints/
├── fastpitch/
│   ├── best_model.pth      # FastPitch acoustic model
│   ├── config.json         # FastPitch configuration
│   └── speakers.pth         # Speaker embeddings (male/female)
└── hifigan/
    ├── best_model.pth      # HiFi-GAN vocoder
    └── config.json         # HiFi-GAN configuration
```

#### Option B: Using Hugging Face (if available)
```bash
# Check if models are available on Hugging Face
# Some IndicTTS models might be available there
```

### 3. Test the Setup
```bash
python test_tamil_tts.py
```

### 4. Run the Main Script
```bash
python murugan_voice_gen.py
```

## 📁 Project Structure

```
Murugan/
├── checkpoints/           # Tamil TTS models (download required)
│   ├── fastpitch/
│   └── hifigan/
├── assets/               # Reference audio files
├── output/               # Generated audio files
├── temp/                 # Temporary processing files
├── murugan_voice_gen.py  # Main script
├── test_tamil_tts.py     # Test script
└── download_models.py    # Model download helper
```

## 🎯 Features

- **Tamil Text-to-Speech**: Uses IndicTTS FastPitch + HiFi-GAN models
- **Baby Voice Effects**: Pitch shifting, reverb, normalization
- **Background Music**: Optional BGM mixing
- **Multiple Formats**: WAV and MP3 output
- **Error Handling**: Comprehensive error checking and logging

## 🔧 Configuration

### Tamil Text Lines
Edit the `LINES` array in `murugan_voice_gen.py`:
```python
LINES = [
    "அன்பே மிகப் பெரிய வலிமை. ஒரு சிறிய உதவும் பெரிய மகிழ்ச்சியை தரும்.",
    "நல்ல சிந்தனைகள் உன்னை உயர்த்தும், தீய சிந்தனைகள் உன்னை தாழ்த்தும்.",
    # Add more Tamil lines...
]
```

### Voice Settings
- **Speaker**: `"female"` or `"male"` (if supported by speakers.pth)
- **Pitch Shift**: `semitones=4` (higher = more baby-like)
- **Reverb**: `add_reverb=True` (adds echo effect)
- **BGM Volume**: `bgm_db=-18` (background music level)

## 🐛 Troubleshooting

### Common Issues

1. **"Missing model files" error**
   - Download the Tamil IndicTTS models from AI4Bharat
   - Ensure files are in the correct directory structure

2. **"TTS synthesizer not initialized" error**
   - Check that all model files are present and not corrupted
   - Verify file paths in the script

3. **Audio quality issues**
   - Ensure you're using the correct Tamil models
   - Check that speakers.pth supports the speaker_name you're using

4. **FFmpeg errors**
   - Install FFmpeg and ensure it's in your PATH
   - Check that input audio files exist

### Model File Requirements

- **FastPitch**: Acoustic model for Tamil speech synthesis
- **HiFi-GAN**: Vocoder for high-quality audio generation
- **Speakers.pth**: Speaker embeddings for voice selection
- **Config files**: Model configuration parameters

## 📚 Resources

- [AI4Bharat IndicTTS Repository](https://github.com/AI4Bharat/Indic-TTS)
- [TTS Library Documentation](https://tts.readthedocs.io/)
- [PyTorch Installation Guide](https://pytorch.org/get-started/locally/)

## 🎵 Output Files

The script generates:
- `murugan_tts_raw_YYYY-MM-DD.wav` - Raw Tamil speech
- `murugan_tts_baby_YYYY-MM-DD.wav` - Baby voice processed
- `murugan_voice_final_YYYY-MM-DD.wav` - Final with BGM
- `murugan_voice_final_YYYY-MM-DD.mp3` - MP3 version

## ⚡ Performance Tips

- Use CPU for smaller models, GPU for faster processing
- Adjust `silence_ms` for different pause lengths between sentences
- Modify `semitones` for different baby voice effects
- Use `bgm_db` to control background music volume

---

**Note**: This setup requires downloading the actual Tamil IndicTTS model files from AI4Bharat. The placeholder files in the checkpoints directory are just for structure reference.








