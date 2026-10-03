# Prepares a fresh Windows machine (the GitHub Actions runner) to run the Shorts pipeline exactly
# as the laptop does: Python packages at the laptop's versions, FFmpeg, the Tamil voice model, and
# the SadTalker code used to find the face and to send to Kaggle. Everything comes from public
# sources; private files (pictures, voice sample, keys) are added by the workflow afterwards.
#
#   ci\setup.ps1            everything
#   ci\setup.ps1 -NoVoice   skip the 1.5 GB voice model (enough for the tests)
param([switch]$NoVoice)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is many times faster without the bar
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Python packages (laptop versions)"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r ci/requirements.txt -c ci/constraints.txt --extra-index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
python -m pip install --quiet --no-deps facexlib==0.3.0
if ($LASTEXITCODE -ne 0) { throw "pip install facexlib failed" }

Write-Host "== FFmpeg (full build: libass captions, rubberband voice pace)"
if (-not (Test-Path "tools/ffmpeg/bin/ffmpeg.exe")) {
    $zip = Join-Path $env:TEMP "ffmpeg.zip"
    Invoke-WebRequest "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath (Join-Path $env:TEMP "ffmpeg") -Force
    New-Item -ItemType Directory -Force "tools/ffmpeg" | Out-Null
    $bin = Get-ChildItem (Join-Path $env:TEMP "ffmpeg") -Directory | Select-Object -First 1
    Copy-Item (Join-Path $bin.FullName "bin") "tools/ffmpeg/bin" -Recurse -Force
}
& "tools/ffmpeg/bin/ffmpeg.exe" -version | Select-Object -First 1

Write-Host "== SadTalker code (the laptop's working copy) and its face models"
if (-not (Test-Path "SadTalker/inference.py")) {
    Expand-Archive "shorts/vendor/sadtalker_code.zip" -DestinationPath $env:TEMP -Force
    Copy-Item (Join-Path $env:TEMP "sadtalker") "SadTalker" -Recurse -Force
}
New-Item -ItemType Directory -Force "SadTalker/gfpgan/weights" | Out-Null
foreach ($f in "alignment_WFLW_4HG.pth", "detection_Resnet50_Final.pth") {
    if (-not (Test-Path "SadTalker/gfpgan/weights/$f")) {
        Invoke-WebRequest "https://github.com/xinntao/facexlib/releases/download/v0.1.0/$f" -OutFile "SadTalker/gfpgan/weights/$f"
    }
}

if (-not $NoVoice) {
    Write-Host "== Tamil voice model (IndicTTS FastPitch + HiFi-GAN, AI4Bharat release)"
    if (-not (Test-Path "checkpoints/fastpitch/best_model.pth")) {
        $zip = Join-Path $env:TEMP "ta.zip"
        Invoke-WebRequest "https://github.com/AI4Bharat/Indic-TTS/releases/download/v1-checkpoints-release/ta.zip" -OutFile $zip
        Expand-Archive $zip -DestinationPath (Join-Path $env:TEMP "ta_model") -Force
        $src = Get-ChildItem (Join-Path $env:TEMP "ta_model") -Recurse -Directory -Filter "fastpitch" | Select-Object -First 1
        New-Item -ItemType Directory -Force "checkpoints" | Out-Null
        Copy-Item $src.FullName "checkpoints/fastpitch" -Recurse -Force
        Copy-Item (Join-Path $src.Parent.FullName "hifigan") "checkpoints/hifigan" -Recurse -Force
        Remove-Item $zip
    }
    # The model's config names its speakers file by absolute path: point it at this machine's copy
    python -c @"
import json, pathlib
p = pathlib.Path('checkpoints/fastpitch/config.json'); c = json.loads(p.read_text(encoding='utf-8'))
spk = str(pathlib.Path('checkpoints/fastpitch/speakers.pth').resolve()).replace('\\', '/')
c['speakers_file'] = spk
if isinstance(c.get('model_args'), dict): c['model_args']['speakers_file'] = spk
p.write_text(json.dumps(c, indent=4, ensure_ascii=False), encoding='utf-8')
print('speakers file ->', spk)
"@
}
Write-Host "== setup done"
