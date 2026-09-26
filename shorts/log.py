"""Logging and per-stage timing, so every run prints (and returns) where the time went."""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager

log = logging.getLogger("shorts")


def setup_logging(verbose: bool = False) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Tamil text on a Windows console
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    log.handlers[:] = [handler]
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.propagate = False


class StageTimer:
    def __init__(self):
        self.times: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str):
        log.info("▶ %s", name)
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            self.times[name] = self.times.get(name, 0.0) + dt
            log.info("✓ %s (%.1f s)", name, dt)

    def summary(self) -> str:
        total = sum(self.times.values())
        rows = [f"  {name:<22} {secs:7.1f} s" for name, secs in self.times.items()]
        return "\n".join(["Stage timings:", *rows, f"  {'TOTAL':<22} {total:7.1f} s"])
