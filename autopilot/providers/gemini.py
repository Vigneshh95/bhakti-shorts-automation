"""Google Gemini over the REST API: JSON text generation, optionally looking at images."""
from __future__ import annotations

import base64
import json

from autopilot.http import ProviderError, post_json
from autopilot.settings import require_key

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def complete_json(model: str, system: str, user: str, schema: dict,
                  images: list[tuple[str, bytes]] | None = None) -> dict:
    """images: optional (label, jpeg bytes) pairs, each sent right after its label so the
    model can refer to them by label."""
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
    headers = {"x-goog-api-key": require_key("GEMINI_API_KEY", "The Gemini provider")}
    resp = post_json(f"{BASE}/{model}:generateContent", body, headers)
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    if not text:
        raise ProviderError(f"Gemini returned no text (finishReason={cand.get('finishReason')}, "
                            f"blocked={resp.get('promptFeedback', {}).get('blockReason')})")
    return json.loads(text)
