"""Writes one story episode: draft -> mechanical checks -> a separate review. Nothing unreviewed
is made into a video. Gemini's free tier, with the same fallback models as the daily Shorts."""
from __future__ import annotations

import json
import tomllib

from autopilot.http import ProviderError
from autopilot.providers import gemini
from shorts.config import ROOT
from shorts.log import log
from stories import script as S

MAX_DRAFTS = 3


def load_settings() -> dict:
    with open(ROOT / "stories.toml", "rb") as f:
        s = tomllib.load(f)
    s["paths"] = {k: ROOT / v for k, v in s["paths"].items()}
    return s


def ask(settings: dict, system: str, user: str, schema: dict, images: list | None = None) -> dict:
    backups = settings["models"].get("gemini_text_fallback") or []
    # Stories make many calls; with their own key (a second Google Cloud project) they don't use up
    # the free daily allowance the daily Shorts depend on. Without one, the shared key is used.
    from autopilot.settings import api_key

    key_name = "GEMINI_API_KEY_STORIES" if api_key("GEMINI_API_KEY_STORIES") else "GEMINI_API_KEY"
    last = None
    for model in [settings["models"]["gemini_text"], *backups]:
        try:
            return gemini.complete_json(model, system, user, schema, images=images, key_name=key_name)
        except (ProviderError, json.JSONDecodeError) as e:
            last = e
            log.warning("  %s unavailable: %s", model, str(e).splitlines()[0][:120])
    raise RuntimeError(f"No model could write the story: {last}")


def write(series: str, topic: str, settings: dict, recent_titles: list[str] | None = None) -> dict:
    system = S.system_prompt(series, settings, topic)
    user = "Write today's episode.\n\n" + S.source_list()
    if recent_titles:
        user += "\nEarlier episodes (tell a different story with a different source line):\n- " + "\n- ".join(recent_titles[-12:])
    audience = "children of 4-10 with a parent" if series == "kids" else "viewers from 15 to 80"
    feedback = ""
    for draft in range(1, MAX_DRAFTS + 1):
        log.info("  writing the story, draft %d", draft)
        data = ask(settings, system, user + feedback, S.SCHEMA)
        problems = S.validate(data, settings)
        if not problems:
            review = ask(settings, S.REVIEW.format(audience=audience), json.dumps(data, ensure_ascii=False, indent=1), S.REVIEW_SCHEMA)
            if review.get("ok"):
                data["series"], data["topic"] = series, topic
                return data
            problems = review.get("issues") or ["the reviewer rejected the script"]
            log.warning("  review rejected the draft: %s", "; ".join(problems)[:400])
        else:
            log.warning("  draft rejected: %s", "; ".join(problems)[:400])
        feedback = ("\n\nYour previous answer had these problems; fix all of them:\n- " + "\n- ".join(problems)
                    + "\nPrevious answer:\n" + json.dumps(data, ensure_ascii=False))
    raise RuntimeError(f"No story passed the checks and review after {MAX_DRAFTS} drafts")
