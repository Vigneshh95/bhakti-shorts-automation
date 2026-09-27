"""Google Gemini: text (JSON) and image generation, over the REST API."""
from __future__ import annotations

import base64
import json

from autopilot.http import ProviderError, post_json
from autopilot.settings import require_key

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _headers() -> dict:
    return {"x-goog-api-key": require_key("GEMINI_API_KEY", "The Gemini provider")}


def complete_json(model: str, system: str, user: str, schema: dict) -> dict:
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema, "temperature": 0.9},
    }
    resp = post_json(f"{BASE}/{model}:generateContent", body, _headers())
    cand = (resp.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise ProviderError(f"Gemini returned no text (finishReason={cand.get('finishReason')}, "
                            f"blocked={resp.get('promptFeedback', {}).get('blockReason')})")
    return json.loads(text)


def generate_image(model: str, prompt: str) -> tuple[bytes, str]:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}},
    }
    resp = post_json(f"{BASE}/{model}:generateContent", body, _headers(), timeout=300)
    for part in (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            return base64.b64decode(inline["data"]), mime
    raise ProviderError(f"Gemini returned no image (finishReason="
                        f"{(resp.get('candidates') or [{}])[0].get('finishReason')})")
