"""OpenAI chat completions (JSON schema) over the REST API -- an optional writer."""
from __future__ import annotations

import json

from autopilot.http import ProviderError, post_json
from autopilot.settings import require_key

BASE = "https://api.openai.com/v1"


def complete_json(model: str, system: str, user: str, schema: dict, images=None) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
    }
    headers = {"Authorization": f"Bearer {require_key('OPENAI_API_KEY', 'The OpenAI provider')}"}
    resp = post_json(f"{BASE}/chat/completions", body, headers)
    msg = resp["choices"][0]["message"]
    if msg.get("refusal"):
        raise ProviderError(f"OpenAI refused: {msg['refusal']}")
    return json.loads(msg["content"])
