"""One shared record between this laptop and the cloud runs (GitHub Actions).

The private repository (a clone lives in .cache/assets_repo) holds what both need to agree on:
the run histories (what was made and uploaded, which picture and chapter were used), the picture
descriptions, the chapter verdicts, each day's reviewed script -- and the pictures themselves, so
a picture added on the laptop is used in the cloud too.

  pull()  before a run: bring the cloud's record here (histories are merged, never overwritten)
  push()  after a run, or after adding pictures: send this laptop's record and pictures up

On the cloud runner there is no clone (the workflow copies the files itself), so both do nothing
there. Any failure (no internet, no clone) is only a warning: a run never stops because of it."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from shorts.config import ROOT
from shorts.log import log

CLONE = ROOT / ".cache" / "assets_repo"
HISTORIES = ["episodes/auto/history.json", "episodes/periyava/history.json", "episodes/ramana/history.json"]
STATE = ["episodes/periyava/playlist.json", "daily_images/.library.json", "periyava_images/.library.json",
         "episodes/ramana/playlist.json", "ramana_images/.library.json",
         "sources/deivathin_kural/verdicts.json"]
PICTURE_FOLDERS = ["daily_images", "periyava_images", "ramana_images"]
PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(CLONE), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600, env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"})


def available() -> bool:
    return (CLONE / ".git").exists()


def merge_histories(ours: list[dict], theirs: list[dict]) -> list[dict]:
    """Every record from both sides, once, in the order they were made."""
    seen, out = set(), []
    for r in [*ours, *theirs]:
        key = json.dumps(r, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return sorted(out, key=lambda r: (r.get("date", ""), r.get("made_at", "")))


def _read(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError:
        return []


def _merge_json_dict(local: Path, remote: Path) -> None:
    """Descriptions / verdicts: keep every entry either side has (they are keyed by content)."""
    try:
        a = json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}
        b = json.loads(remote.read_text(encoding="utf-8")) if remote.exists() else {}
    except ValueError:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        merged = {**b, **a}
        text = json.dumps(merged, ensure_ascii=False, indent=1)
        for p in (local, remote):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")


def _merge_state() -> None:
    for rel in HISTORIES:
        merged = merge_histories(_read(ROOT / rel), _read(CLONE / rel))
        if merged:
            text = json.dumps(merged, ensure_ascii=False, indent=1)
            for p in (ROOT / rel, CLONE / rel):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
    for rel in STATE:
        if rel.endswith("playlist.json"):
            src, dst = (CLONE / rel, ROOT / rel) if (CLONE / rel).exists() else (ROOT / rel, CLONE / rel)
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
        else:
            _merge_json_dict(ROOT / rel, CLONE / rel)
    # the story pipeline's records (script + release slot of each story: small files; pictures and
    # videos stay where they were made), so laptop and cloud never tell the same topic or take the
    # same release slot twice
    for side_a, side_b in ((CLONE, ROOT), (ROOT, CLONE)):
        for series in ("adults", "kids"):
            for record in (side_a / "story_episodes").glob(f"{series}-*/*.json"):
                if record.name in ("script.json", "published.json"):
                    target = side_b / record.relative_to(side_a)
                    if not target.exists() or (record.name == "script.json" and record.stat().st_mtime > target.stat().st_mtime
                                               and record.read_bytes() != target.read_bytes()):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(record, target)
    # each day's reviewed script: whichever side wrote it first is used by the other
    for side_a, side_b in ((CLONE, ROOT), (ROOT, CLONE)):
        for script in (side_a / "episodes").glob("*/*/script.json"):
            target = side_b / script.relative_to(side_a)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(script, target)


def pull() -> bool:
    if not available():
        return False
    try:
        res = _git("pull", "-q", "--no-rebase")
        if res.returncode != 0:
            log.warning("  couldn't read the shared history (%s); using this laptop's own",
                        (res.stderr or res.stdout).strip().splitlines()[-1:] or "?")
            return False
        _merge_state()
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("  couldn't read the shared history (%s); using this laptop's own", e)
        return False


def push(pictures: bool = True) -> bool:
    """Sends the record (and, by default, the picture folders exactly as they are here) up."""
    if not available():
        return False
    try:
        _git("pull", "-q", "--no-rebase")
        _merge_state()
        if pictures:
            for folder in PICTURE_FOLDERS:
                here = {p.name: p for p in (ROOT / folder).iterdir() if p.suffix.lower() in PICTURE_EXTS} \
                    if (ROOT / folder).is_dir() else {}
                (CLONE / folder).mkdir(parents=True, exist_ok=True)
                there = {p.name: p for p in (CLONE / folder).iterdir() if p.suffix.lower() in PICTURE_EXTS}
                for name, p in here.items():
                    if name not in there or there[name].stat().st_size != p.stat().st_size:
                        shutil.copyfile(p, CLONE / folder / name)
                for name in there.keys() - here.keys():   # removed here: removed for the cloud too
                    (CLONE / folder / name).unlink()
                credits = ROOT / folder / "credits.json"
                if credits.exists():
                    shutil.copyfile(credits, CLONE / folder / "credits.json")
        _git("add", "-A")
        if _git("diff", "--cached", "--quiet").returncode == 0:
            return True
        _git("-c", "user.name=laptop", "-c", "user.email=laptop@users.noreply.github.com", "commit", "-q", "-m",
             "laptop: history and pictures")
        res = _git("push", "-q")
        if res.returncode != 0:
            log.warning("  couldn't save to the shared history (%s); it will go up with the next run",
                        (res.stderr or res.stdout).strip().splitlines()[-1:] or "?")
            return False
        return True
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("  couldn't save to the shared history (%s); it will go up with the next run", e)
        return False
