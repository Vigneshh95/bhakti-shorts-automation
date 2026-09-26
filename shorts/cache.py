"""Content-addressed cache: a file's name is the hash of everything that produced it
(inputs + settings + a version tag), so a changed input automatically misses and an
unchanged one is reused. Deleting the .cache folder is always safe."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class Cache:
    def __init__(self, root: Path):
        self.root = root
        self.hits = 0
        self.misses = 0

    def key(self, kind: str, *parts) -> str:
        h = hashlib.sha256(kind.encode())
        for part in parts:
            if isinstance(part, Path):
                h.update(file_digest(part).encode())
            else:
                h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode())
        return h.hexdigest()[:24]

    def path(self, kind: str, key: str, suffix: str) -> Path:
        d = self.root / kind
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}{suffix}"

    def lookup(self, kind: str, key: str, suffix: str) -> tuple[Path, bool]:
        p = self.path(kind, key, suffix)
        if p.exists() and p.stat().st_size > 0:
            self.hits += 1
            return p, True
        self.misses += 1
        return p, False


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
