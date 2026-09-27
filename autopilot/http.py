"""Tiny JSON-over-HTTPS helper with retries for rate limits / server errors (no extra deps)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from shorts.log import log


class ProviderError(RuntimeError):
    pass


def _quota_problem(raw: str) -> str | None:
    """Classifies a 429 from Google or OpenAI. Returns None for a plain rate limit,
    "per-minute" for a short Google quota (worth waiting for), or a permanent-for-today reason."""
    try:
        err = json.loads(raw).get("error", {})
    except (ValueError, AttributeError):
        return None
    if err.get("code") == "insufficient_quota" or err.get("type") == "insufficient_quota" or "credit" in str(err.get("code", "")):
        return "account has no credit left -- add credit in the provider's billing page"
    violations = [v for d in err.get("details", []) if str(d.get("@type", "")).endswith("QuotaFailure")
                  for v in d.get("violations", [])]
    if not violations:
        return None
    ids = [str(v.get("quotaId", "")) for v in violations]
    if all("FreeTier" in i for i in ids) and not any(v.get("quotaValue") for v in violations):
        return "this model isn't available on the free tier -- enable billing on the API key (Google AI Studio)"
    if any("PerDay" in i for i in ids):
        return "today's free quota for this model is used up (resets daily)"
    return "per-minute"


def _retry_delay(raw: str) -> int:
    try:
        for d in json.loads(raw).get("error", {}).get("details", []):
            if str(d.get("@type", "")).endswith("RetryInfo"):
                return min(120, int(float(str(d.get("retryDelay", "0s")).rstrip("s"))) + 1)
    except (ValueError, AttributeError):
        pass
    return 0


def post_json(url: str, body: dict, headers: dict, timeout: int = 180, retries: int = 3) -> dict:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            detail = raw[:600]
            host = url.split("/")[2]
            quota = _quota_problem(raw) if e.code == 429 else None
            if quota and quota != "per-minute":
                raise ProviderError(f"{host}: {quota}") from e  # retrying today can't help
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = _retry_delay(raw) or int(e.headers.get("retry-after", 0) or 0) or 5 * 2 ** attempt
                log.warning("  %s returned %d, retrying in %ds", url.split("/")[2], e.code, wait)
                time.sleep(wait)
                continue
            raise ProviderError(f"HTTP {e.code} from {url.split('?')[0]}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(5 * 2 ** attempt)
                continue
            raise ProviderError(f"Network error calling {url.split('?')[0]}: {e}") from e
    raise ProviderError("unreachable")
