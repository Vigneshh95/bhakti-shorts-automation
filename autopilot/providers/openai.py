"""OpenAI: text (JSON schema) and image generation, over the REST API."""
from __future__ import annotations

import base64
import json

from autopilot.http import ProviderError, post_json
from autopilot.settings import require_key

BASE = "https://api.openai.com/v1"


def _headers() -> dict:
    return {"Authorization": f"Bearer {require_key('OPENAI_API_KEY', 'The OpenAI provider')}"}


def complete_json(model: str, system: str, user: str, schema: dict) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
    }
    resp = post_json(f"{BASE}/chat/completions", body, _headers())
    msg = resp["choices"][0]["message"]
    if msg.get("refusal"):
        raise ProviderError(f"OpenAI refused: {msg['refusal']}")
    return json.loads(msg["content"])


def generate_image(model: str, prompt: str) -> tuple[bytes, str]:
    body = {"model": model, "prompt": prompt, "size": "1024x1536", "n": 1}
    resp = post_json(f"{BASE}/images/generations", body, _headers(), timeout=300)
    item = (resp.get("data") or [{}])[0]
    if not item.get("b64_json"):
        raise ProviderError("OpenAI returned no image data")
    return base64.b64decode(item["b64_json"]), "image/png"
