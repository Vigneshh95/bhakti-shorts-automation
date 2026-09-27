"""Optional last step: upload the Short that was just made, using the existing uploader
(autouploadmurugan.py) unchanged -- same config.ini, OAuth token, title/tag/description
generator and playlist. The difference from running upload_short.bat is that this
uploads exactly the file just rendered, instead of guessing "today's newest video"."""
from __future__ import annotations

import sys
from pathlib import Path

from shorts.config import ROOT
from shorts.log import log

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"


def build_metadata(video: Path):
    up = _uploader_module()
    config = up.Config(ROOT / "config.ini")
    config.scopes = YOUTUBE_SCOPE
    meta = up.MetadataGenerator(config)
    highlight = meta.extract_highlight(video)  # reads the .txt the pipeline writes next to the video
    title = meta.choose_title(highlight)
    tags = meta.make_tag_list(highlight)
    return up, config, title, tags, meta.build_description(highlight, title, tags)


def upload_video(video: Path, dry_run: bool = False) -> str | None:
    up, config, title, tags, description = build_metadata(video)
    log.info("YouTube metadata for %s:\n  title: %s\n  tags (%d): %s\n  description:\n%s",
             video.name, title, len(tags), ", ".join(tags[:12]), "    " + description.replace("\n", "\n    "))
    if dry_run:
        log.info("Dry run: nothing uploaded.")
        return None

    uploader = up.YouTubeUploader(config)  # opens the browser for sign-in only if the token is missing/expired
    video_id = uploader.upload(video, title, description, tags)
    if not video_id:
        raise RuntimeError("YouTube upload failed -- see the uploader's message above.")
    uploader.add_to_playlist(video_id)
    log.info("✅ Uploaded: https://youtu.be/%s", video_id)
    return video_id


def _uploader_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import autouploadmurugan

    return autouploadmurugan
