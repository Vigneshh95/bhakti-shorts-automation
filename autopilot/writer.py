"""Writes and reviews the day's script: draft -> validate (retry with the exact problems fed
back) -> independent review pass. Nothing unreviewed is published.

Resilience for unattended runs: the main writer's model can fall back to a second model of the
same provider (e.g. when it's overloaded), and the whole step can fall back to a second
provider ([providers] fallback_writer)."""
from __future__ import annotations

import json

from autopilot import script as S
from autopilot.http import ProviderError
from autopilot.planner import Plan
from shorts.log import log

MAX_ATTEMPTS = 4  # content retries; switching to a fallback model after an outage uses one too


class NoPublishableScript(RuntimeError):
    pass


def _provider(name: str):
    if name == "gemini":
        from autopilot.providers import gemini as p
    elif name == "openai":
        from autopilot.providers import openai as p
    elif name == "claude":
        from autopilot.providers import claude as p
    else:
        raise ValueError(f"Unknown writer provider '{name}' (use gemini, claude or openai)")
    return p


def write_script(plan: Plan, settings: dict, recent_titles: list[str]) -> S.Script:
    order = [settings["providers"]["writer"]]
    backup = settings["providers"].get("fallback_writer")
    if backup and backup not in order:
        order.append(backup)
    last: Exception | None = None
    for name in order:
        try:
            return _write_with(name, plan, settings, recent_titles)
        except NoPublishableScript:
            raise  # the model worked but the content never passed review: another provider won't be "safer"
        except (ProviderError, json.JSONDecodeError, RuntimeError) as e:
            last = e
            log.warning("  writer '%s' unavailable: %s", name, str(e).splitlines()[0][:200])
    raise RuntimeError(f"No writer could produce a script ({', '.join(order)}): {last}")


def _write_with(name: str, plan: Plan, settings: dict, recent_titles: list[str]) -> S.Script:
    provider = _provider(name)
    backups = settings["models"].get(f"{name}_text_fallback") or []
    models = [settings["models"][f"{name}_text"], *([backups] if isinstance(backups, str) else backups)]
    model = models[0]
    system, user = S.build_prompt(plan, settings, recent_titles)

    feedback, rejected = "", False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log.info("  writing script with %s (%s), attempt %d", name, model, attempt)
        try:
            data = provider.complete_json(model, system, user + feedback, S.SCHEMA)
            problems = S.validate(data, settings)
            if problems:
                rejected = True
                log.warning("  draft rejected: %s", "; ".join(problems))
                feedback = ("\n\nYour previous answer had these problems; fix all of them:\n- " + "\n- ".join(problems)
                            + "\nPrevious answer:\n" + json.dumps(data, ensure_ascii=False))
                continue
            review = provider.complete_json(model, S.REVIEW_SYSTEM, json.dumps(data, ensure_ascii=False, indent=1),
                                            S.REVIEW_SCHEMA)
        except (ProviderError, json.JSONDecodeError) as e:
            log.warning("  %s failed: %s", model, str(e).splitlines()[0][:200])
            if model != models[-1]:
                model = models[models.index(model) + 1]
                log.info("  switching to fallback model %s", model)
            elif attempt == MAX_ATTEMPTS or not rejected:
                raise
            continue

        if review.get("ok"):
            result = S.to_script(data, f"{name}:{model}")
            result.review_issues = review.get("issues", [])
            return result
        rejected = True
        issues = review.get("issues") or ["reviewer rejected the script"]
        log.warning("  review rejected the draft: %s", "; ".join(issues))
        feedback = ("\n\nAn editor rejected your previous answer for these reasons; write a new version that fixes them:\n- "
                    + "\n- ".join(issues) + "\nPrevious answer:\n" + json.dumps(data, ensure_ascii=False))

    if rejected:
        raise NoPublishableScript(f"No script passed checks and review after {MAX_ATTEMPTS} attempts -- "
                                  "nothing was made or uploaded.")
    raise ProviderError(f"{name}: no response after {MAX_ATTEMPTS} attempts")
