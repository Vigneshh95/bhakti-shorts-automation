"""The repository is public: no key, token or sign-in may ever be in a tracked file."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "Google API key": r"AIza[0-9A-Za-z_\-]{30,}",
    "Google OAuth client secret": r"GOCSPX-[0-9A-Za-z_\-]{10,}",
    "Google refresh token": r"1//0[0-9A-Za-z_\-]{30,}",
    "Google access token": r"ya29\.[0-9A-Za-z_\-]{20,}",
    "GitHub token": r"(ghp|gho|ghu|ghs)_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{30,}",
    "Hugging Face token": r"hf_[0-9A-Za-z]{30,}",
    "Kaggle token": r"KGAT_[0-9A-Za-z]{20,}",
    "OpenAI / Anthropic key": r"sk-(ant-)?[0-9A-Za-z_\-]{30,}",
    "private key": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
}
NEVER_TRACKED = [".env", "client_secret.json", "murugan_token.json", "kids_token.json", "youtube_token.json",
                 "sign_in_files/1_BrahmaNadagam_YouTube_sign_in.json", "sign_in_files/2_Kids_channel_YouTube_sign_in.json", "sign_in_files/3_Google_app_client_secret.json"]


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


def test_no_key_or_token_in_any_tracked_file():
    hits = []
    for path in _tracked():
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".flac", ".zip", ".pt", ".pth", ".ttf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in PATTERNS.items():
            if re.search(pattern, text):
                hits.append(f"{path.relative_to(ROOT)}: looks like a {name}")
    assert not hits, "Remove these from the repository and renew the keys:\n" + "\n".join(hits)


def test_sign_in_and_key_files_are_never_tracked():
    tracked = {p.relative_to(ROOT).as_posix() for p in _tracked()} | {p.name for p in _tracked()}
    assert not tracked & set(NEVER_TRACKED), f"tracked by git: {tracked & set(NEVER_TRACKED)}"
    ignored = subprocess.run(["git", "check-ignore", *NEVER_TRACKED], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert set(ignored) == set(NEVER_TRACKED), f"not ignored by .gitignore: {set(NEVER_TRACKED) - set(ignored)}"
