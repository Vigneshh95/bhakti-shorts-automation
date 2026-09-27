"""Anthropic Claude as the script writer (text only -- Claude doesn't generate images).

Uses the official `anthropic` SDK with structured outputs, so the reply is guaranteed to be
JSON matching the schema. Server-side refusal fallbacks are enabled (`fallbacks="default"`),
so if Claude Opus 5 declines a request the API retries it on a fallback model in the same call.
Credentials: ANTHROPIC_API_KEY from the environment / .env, or an `ant auth login` profile."""
from __future__ import annotations

import json

from autopilot.http import ProviderError
from autopilot.settings import api_key


def complete_json(model: str, system: str, user: str, schema: dict) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise ProviderError("The Claude writer needs the anthropic package: "
                            ".venv\\Scripts\\python.exe -m pip install anthropic") from e

    key = api_key("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise ProviderError("Claude: invalid or missing API key (set ANTHROPIC_API_KEY in .env)") from e
    except anthropic.RateLimitError as e:
        raise ProviderError("Claude: rate limited, try again later") from e
    except anthropic.APIStatusError as e:
        raise ProviderError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ProviderError("Claude: network error") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ProviderError(f"Claude declined this request (category: {category})")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise ProviderError(f"Claude returned no text (stop_reason={response.stop_reason})")
    return json.loads(text)
