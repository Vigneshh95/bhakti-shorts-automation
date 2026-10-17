"""Google Gemini over the REST API: JSON text generation, optionally looking at images."""
from __future__ import annotations

import base64
import json
import re

from autopilot.http import ProviderError, post_json
from autopilot.settings import require_key

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_AVAILABLE: dict[str, list[str]] = {}


def available_models(key: str) -> list[str]:
    """The model names this key can use today (asked once per run). Empty if Google can't be asked."""
    if key not in _AVAILABLE:
        import urllib.request

        names: list[str] = []
        try:
            url = f"{BASE}?pageSize=500"
            req = urllib.request.Request(url, headers={"x-goog-api-key": key})
            for m in json.load(urllib.request.urlopen(req, timeout=60)).get("models", []):
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    names.append(m["name"].split("/", 1)[1])
        except Exception:  # noqa: BLE001 -- offline or busy: use the configured names as they are
            names = []
        _AVAILABLE[key] = names
    return _AVAILABLE[key]


def _version(name: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", name.split("-")[1] if "-" in name else "0")[:2] or [0])


def newest(key: str, kind: str = "text") -> list[str]:
    """Models that can stand in when a configured one has been retired by Google: the newest
    "flash" models of the kind wanted (text, or speech), best first."""
    out = []
    for name in available_models(key):
        if not name.startswith("gemini-") or "flash" not in name:
            continue
        speech = name.endswith("-tts") or "-tts-" in name
        if (kind == "speech") != speech or any(x in name for x in ("image", "audio", "live", "embedding", "thinking")):
            continue
        out.append(name)
    return sorted(out, key=lambda n: ("lite" in n, "preview" in n, tuple(-v for v in _version(n))))


def resolve(model: str, key: str, kind: str = "text") -> str:
    """The configured model if Google still offers it; otherwise its newest replacement (so a model
    retired while nobody is watching doesn't stop the daily runs)."""
    names = available_models(key)
    if not names or model in names:
        return model
    stand_in = newest(key, kind)
    return stand_in[0] if stand_in else model


def complete_json(model: str, system: str, user: str, schema: dict,
                  images: list[tuple[str, bytes]] | None = None, key_name: str = "GEMINI_API_KEY") -> dict:
    """images: optional (label, jpeg bytes) pairs, each sent right after its label so the
    model can refer to them by label. key_name: which key in .env to use (the free quota is per
    Google Cloud project, so a second project's key gives a second daily allowance)."""
    parts: list[dict] = []
    for label, jpeg in images or []:
        parts.append({"text": f"Image {label}:"})
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}})
    parts.append({"text": user})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema, "temperature": 0.9},
    }
    key = require_key(key_name, "The Gemini provider")
    headers = {"x-goog-api-key": key}
    resp = post_json(f"{BASE}/{resolve(model, key)}:generateContent", body, headers)
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text:
        raise ProviderError(f"Gemini returned no text (finishReason={cand.get('finishReason')}, "
                            f"blocked={resp.get('promptFeedback', {}).get('blockReason')})")
    return json.loads(text)
