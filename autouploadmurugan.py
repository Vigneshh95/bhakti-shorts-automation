#!/usr/bin/env python3
"""
Murugan Shorts Auto-Uploader (Temple Tamil Channel)

This script automates the entire process of uploading a YouTube Short to the
Murugan channel. It performs the following steps:

1.  **Finds Today's Video**: Locates the video file for the current day in the
    specified 'Final' directory. It can find files by date in the filename
    or by modification date.
2.  **Generates SEO-Optimized Metadata**:
    - Picks a random, engaging title from a large, pre-defined pool.
    - Extracts a "highlight" from an accompanying text file or the video's filename.
    - Creates a diverse set of tags/keywords in both Tamil and English.
    - Constructs a bilingual description optimized for discovery and engagement.
3.  **Authenticates with YouTube**: Uses OAuth 2.0 to securely connect to the
    YouTube Data API. It handles token creation and refresh automatically.
4.  **Uploads the Video**: Uploads the video to YouTube, setting the title,
    description, tags, category, and privacy status.
5.  **Adds to Playlist (Optional)**: If a playlist ID is provided in the config,
    the script adds the newly uploaded video to it.

Configuration is managed in the `config.ini` file, allowing for easy updates
without modifying the code. A `DRY_RUN` mode is available to preview metadata
without performing the actual upload.
"""

import os
import re
import random
import time
import logging
import configparser
from pathlib import Path
from datetime import datetime, date

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# --- Basic Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
# --- Constants ---
MAX_TAG_CHARS = 480  # YouTube limit is 500, leave some buffer
YOUTUBE_TITLE_LIMIT = 100
ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")
SCRIPT_DIR = Path(__file__).parent.resolve()


class Config:
    """Loads and manages configuration from config.ini."""

    def __init__(self, config_path):
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found at: {config_path}")

        self.config = configparser.ConfigParser()
        self.config.read(config_path, encoding="utf-8")
        logging.info(f"Configuration loaded from {config_path}")

        # Paths
        self.video_dir = SCRIPT_DIR / self.config.get("Paths", "video_dir", fallback="Final")
        self.client_secrets = SCRIPT_DIR / self.config.get("Paths", "client_secrets", fallback="client_secrets.json")
        self.token_file = SCRIPT_DIR / self.config.get("Paths", "token_file", fallback="token.json")

        # YouTube Settings
        self.playlist_id = self.config.get("YouTube", "playlist_id", fallback=None)
        self.category_id = self.config.get("YouTube", "category_id", fallback="22")
        self.privacy_status = self.config.get("YouTube", "privacy_status", fallback="public")
        self.common_hashtags = self.config.get("YouTube", "common_hashtags", fallback="#Shorts")

        # Social Media
        self.instagram_url = self.config.get("Social", "instagram_url", fallback="")
        self.support_url = self.config.get("Social", "support_url", fallback="")
        self.ig_hashtags = self.config.get("Social", "ig_hashtags", fallback="#Shorts")

        # Ensure directories exist
        self.video_dir.mkdir(exist_ok=True)


class MetadataGenerator:
    """Generates titles, tags, and descriptions for the video."""

    # Title templates with placeholders:
    TITLE_TEMPLATES = [
        "{opener} — {highlight} | முருகன் அருள்",
        "{opener} | {highlight} | Jai Murugan!",
        "{opener} | {highlight} — 50s Murugan Short",
        "{opener} | {highlight} | Murugan Blessing (Tamil)",
        "{opener} | {highlight} | #முருகன் #Shorts",
        "{opener} — {highlight} | Daily Murugan Blessing",
        "{opener} | {highlight} | Temple Wisdom in Tamil",
        "{opener} — {highlight} | Quick Murugan Blessing",
        "{opener} | {highlight} — Vel Muruga Darshan",
        "{opener} | {highlight} | Short & Powerful",
        "{opener} — {highlight} | Devotion in 50s",
        "{opener} | {highlight} | ஆன்மீக அருள்",
        "{opener} — {highlight} | கேளுங்கள், வாழுங்கள்",
        "{opener} | {highlight} | தமிழ் பக்தி Short",
        "{opener} — {highlight} | Boost Your Day",
        "{opener} | {highlight} — Blessings for Today",
        "{opener} — {highlight} | Murugan Quote Today",
        "{opener} | {highlight} | Short Temple Lesson",
        "{opener} — {highlight} | Murugan's Guidance",
        "{opener} | {highlight} — Heartfelt Devotion",
    ]

    TAMIL_OPENERS = [
        "மிக முக்கியம்!", "முருகனின் அருள்", "இன்றைய ஆசீர்", "இந்த வாக்கியம் உங்கள் வாழ்வை மாற்றும்",
        "ஆசீர்வாதம் பெறுங்கள்", "இன்றைய ஸ்பெஷல்", "உயிரின் வழி",
        "எளிய சிந்தனை, பெரிய மாற்றம்", "முருகனின் சிந்தனை", "திருக்குரல்", "வேல் அருள்",
        "நாளை நல்ல நாள்", "அருள் பெறு", "சிறு அறிவுரை", "இன்றைய ஆசி",
    ]
    # Numbered fillers ("முருகன் அருள் 7", "Daily Boost #6", "MuruganTag5") were removed:
    # they read as spam in titles and as tag stuffing to YouTube, and add no search value.

    ENGLISH_OPENERS = [
        "Must Watch!", "Daily Murugan Wisdom", "Quick Blessing", "Instant Calm", "Powerful Truth",
        "Life-Changing Verse", "Short Divine Tip", "Tiny Temple Teaching", "Blessing for Today",
        "Unlock Peace", "One Line That Helps", "Spiritual Boost", "Quick Murugan Advice",
    ]

    TAG_POOL_TAMIL = [
        "முருகன்", "வேல்", "கார்த்திகேயன்", "சுப்பிரமணியர்", "திருமுருகன்", "தமிழ் பக்தி", "தீபம்",
        "பஜனை", "அருள்", "திருப்புகழ்", "பூஜை", "அர்ச்சனை", "அறுபடை வீடு", "ஞானம்",
        "தைப்பூசம்", "கந்த சஷ்டி", "பழனி", "திருச்செந்தூர்", "வேல் முருகா", "கந்தன்",
    ]

    TAG_POOL_EN = [
        "Murugan", "Vel", "Skanda", "Subramanya", "Kartikeya", "TamilBhakti", "Hinduism",
        "Devotional", "Temple", "Shorts", "Spirituality", "Prayer", "Meditation", "Blessing",
        "DailyShorts", "Inspiration", "BhaktiSongs", "TamilShorts", "Religious",
    ]

    def __init__(self, config: Config):
        self.config = config
        self.title_pool = self._build_title_pool()
        self.tag_pool = self.TAG_POOL_TAMIL + self.TAG_POOL_EN + [
            "Murugan Temple", "JaiMurugan", "VelMuruga", "TamilDevotion", "BhaktiShorts",
            "TempleVibes", "SpiritualShorts", "DailyBlessing"
        ]

    def _build_title_pool(self):
        """Generates a large, unique pool of title templates."""
        pool = set()
        # Add permutations (to a copy: extending the class-level list itself made it grow
        # by 4 entries every time a MetadataGenerator was created)
        templates = self.TITLE_TEMPLATES + [
            "{tamil_opener} | {highlight} — {eng_opener}",
            "{eng_opener} — {highlight} | {tamil_opener}",
            "{tamil_opener} — {highlight} | #முருகன்",
            "{eng_opener} | {highlight} | Temple Short",
        ]

        for _ in range(400):  # Generate a large number of variations
            template = random.choice(templates)
            formatted_template = template.format(
                opener=random.choice(self.TAMIL_OPENERS + self.ENGLISH_OPENERS),
                tamil_opener=random.choice(self.TAMIL_OPENERS),
                eng_opener=random.choice(self.ENGLISH_OPENERS),
                highlight="{highlight}"
            )
            pool.add(formatted_template)
        return list(pool)

    def extract_highlight(self, video_path: Path) -> str:
        """Extracts a highlight sentence from a text file or the filename."""
        # Try to find a companion text file (.txt, .md)
        for ext in (".txt", ".md"):
            script_file = video_path.with_suffix(ext)
            if script_file.exists():
                with open(script_file, "r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s:
                            logging.info(f"Found highlight in {script_file.name}: '{s}'")
                            return s[:120]
        # Fallback: infer from filename
        fname = video_path.stem
        cleaned = re.sub(r"(\d{4}[-_]\d{2}[-_]\d{2})|(\d{8})|(\d{2}[-_]\d{2}[-_]\d{4})", "", fname)
        cleaned = cleaned.replace("_", " ").replace("-", " ").strip()
        logging.info(f"Using cleaned filename as highlight: '{cleaned}'")
        return cleaned if cleaned else "முருகன் அருள் / Murugan Blessing"

    def choose_title(self, highlight: str) -> str:
        """Chooses a random title and formats it."""
        template = random.choice(self.title_pool)
        title = template.replace("{highlight}", highlight)
        return title[:YOUTUBE_TITLE_LIMIT]

    def make_tag_list(self, highlight: str) -> list[str]:
        """Creates a list of tags from the highlight and tag pools."""
        # Extract words from highlight
        words = re.split(r"[,\s]+", re.sub(r"[^\w\u0B80-\u0BFF0-9a-zA-Z]", " ", highlight))
        tags = [w for w in words if w]

        # Add unique tags from the pool, shuffled for variety
        shuffled_pool = random.sample(self.tag_pool, len(self.tag_pool))
        
        char_count = sum(len(t) + 1 for t in tags)
        for t in shuffled_pool:
            if t not in tags:
                if char_count + len(t) + 1 > MAX_TAG_CHARS:
                    break
                tags.append(t)
                char_count += len(t) + 1
        
        return tags[:60]  # Hard limit on the number of tags

    def build_description(self, highlight: str, title: str, tags: list[str]) -> str:
        """Builds the full video description."""
        tag_string = ", ".join(tags[:15]) # Show a limited number of tags in description
        
        description_parts = [
            f"{title}\n",
            f"{highlight}\n",
            "🌸 ஜெய் முருகன்! வீடியோவை பகிரவும், லைக் செய்யவும் மற்றும் சப்ஸ்கிரைப் செய்யவும்.",
            "🌟 Daily Murugan blessings in Tamil — Subscribe for more temple shorts.\n",
            f"🎯 Tags/Keywords: {tag_string}\n",
            "👇 Follow & Support",
        ]

        if self.config.instagram_url:
            description_parts.append(f"Instagram: {self.config.instagram_url}")
        if self.config.support_url:
            description_parts.append(f"Donate / Support: {self.config.support_url}")

        description_parts.append(f"\n{self.config.common_hashtags}")
        
        return "\n".join(description_parts)


class YouTubeUploader:
    """Handles YouTube authentication, video upload, and playlist management."""

    def __init__(self, config: Config):
        self.config = config
        self.youtube = self._authenticate()

    def _authenticate(self) -> build:
        """Authenticates with the YouTube API."""
        creds = None
        if self.config.token_file.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.config.token_file), [self.config.scopes])
            except Exception as e:
                logging.warning(f"Could not read token file: {e}. Re-authenticating.")

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(self.config.token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                logging.info("OAuth token has been refreshed.")
            except Exception as e:
                logging.error(f"Token refresh failed: {e}. Please re-authenticate.")
                creds = None

        if not creds or not creds.valid:
            logging.info("Initiating new user authentication flow.")
            flow = InstalledAppFlow.from_client_secrets_file(str(self.config.client_secrets), [self.config.scopes])
            creds = flow.run_local_server(port=0)
            with open(self.config.token_file, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            logging.info(f"New token saved to {self.config.token_file}")

        return build("youtube", "v3", credentials=creds)

    def find_video_to_upload(self) -> Path | None:
        """Finds the most relevant video file to upload from the video directory."""
        if not self.config.video_dir.is_dir():
            logging.error(f"Video directory not found: {self.config.video_dir}")
            return None

        files = sorted(
            [p for p in self.config.video_dir.iterdir() if p.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS],
            key=os.path.getmtime,
            reverse=True
        )

        if not files:
            logging.warning("No video files found in the directory.")
            return None

        today = date.today()
        date_patterns = [
            today.strftime("%Y-%m-%d"), today.strftime("%Y%m%d"),
            today.strftime("%d-%m-%Y"), today.strftime("%d%m%Y"), today.strftime("%d_%m_%Y")
        ]

        # 1. Find by filename containing today's date
        for f in files:
            for pattern in date_patterns:
                if pattern in f.name:
                    logging.info(f"Found video by date in filename: {f.name}")
                    return f

        # 2. Fallback: find by modification date being today
        latest_file = files[0]
        mod_date = datetime.fromtimestamp(latest_file.stat().st_mtime).date()
        if mod_date == today:
            logging.info(f"Found video by modification date: {latest_file.name}")
            return latest_file

        # 3. Final fallback: return the absolute latest file
        logging.warning("No video for today found. Falling back to the latest modified video.")
        return latest_file

    def upload(self, video_path: Path, title: str, description: str, tags: list[str]) -> str | None:
        """Uploads a single video to YouTube."""
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": self.config.category_id,
            },
            "status": {
                "privacyStatus": self.config.privacy_status,
                "madeForKids": False,
                "selfDeclaredMadeForKids": False,
            }
        }
        
        try:
            media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
            request = self.youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            
            logging.info(f"Uploading '{video_path.name}'...")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logging.info(f"Upload progress: {int(status.progress() * 100)}%")
            
            logging.info("✅ Upload successful!")
            video_id = response.get("id")
            return video_id

        except Exception as e:
            logging.error(f"❌ Upload failed: {e}")
            return None

    def add_to_playlist(self, video_id: str):
        """Adds a video to a specified playlist."""
        if not self.config.playlist_id:
            return
        
        try:
            self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": self.config.playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id}
                    }
                }
            ).execute()
            logging.info(f"✅ Successfully added video to playlist {self.config.playlist_id}")
        except Exception as e:
            logging.warning(f"⚠️ Could not add to playlist: {e}")


def main():
    """Main execution function."""
    # --- Configuration ---
    DRY_RUN = False  # Set to True to preview metadata without uploading

    try:
        config = Config(SCRIPT_DIR / "config.ini")
        # Add scopes to config object dynamically
        config.scopes = "https://www.googleapis.com/auth/youtube"
    except FileNotFoundError as e:
        logging.error(e)
        return

    # --- Find Video ---
    uploader = YouTubeUploader(config)
    video_path = uploader.find_video_to_upload()
    if not video_path:
        logging.error("No video found to upload. Please place a video in the 'Final' folder.")
        return

    # --- Generate Metadata ---
    meta_gen = MetadataGenerator(config)
    highlight = meta_gen.extract_highlight(video_path)
    title = meta_gen.choose_title(highlight)
    tags = meta_gen.make_tag_list(highlight)
    description = meta_gen.build_description(highlight, title, tags)

    # --- Preview ---
    print("\n" + "="*20 + " METADATA PREVIEW " + "="*20)
    print(f"Video Path:    {video_path}")
    print(f"Title:         {title}")
    print(f"Tags ({len(tags)}):      {tags[:20]}")
    print("-" * 60)
    print("Description:")
    print(description)
    print("="*62 + "\n")

    if DRY_RUN:
        logging.info("DRY_RUN is enabled. No upload will be performed.")
        return

    # --- Upload ---
    video_id = uploader.upload(video_path, title, description, tags)
    
    if video_id:
        video_url = f"https://youtu.be/{video_id}"
        logging.info(f"Video URL: {video_url}")

        uploader.add_to_playlist(video_id)

        # --- Share Text ---
        print("\n" + "="*20 + " SHARE TEXT " + "="*20)
        print(title)
        print(highlight)
        print(config.ig_hashtags)
        print(f"Watch: {video_url}")
        print("="*52 + "\n")

if __name__ == "__main__":
    main()
