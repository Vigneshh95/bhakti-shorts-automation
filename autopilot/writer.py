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

MAX_DRAFTS = 3  # chances to fix the script's content (outages don't count against these)


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


def write_script(plan: Plan, settings: dict, recent_titles: list[str], pictures: list[tuple[str, str]]) -> S.Script:
    """pictures: (image_id, description) of today's candidate pictures; the writer picks one."""
    order = [settings["providers"]["writer"]]
    backup = settings["providers"].get("fallback_writer")
    if backup and backup not in order:
        order.append(backup)
    last: Exception | None = None
    for name in order:
        try:
            return _write_with(name, plan, settings, recent_titles, pictures)
        except NoPublishableScript:
            raise  # the model worked but the content never passed review: another provider won't be "safer"
        except (ProviderError, json.JSONDecodeError, RuntimeError) as e:
            last = e
            log.warning("  writer '%s' unavailable: %s", name, str(e).splitlines()[0][:200])
    raise RuntimeError(f"No writer could produce a script ({', '.join(order)}): {last}")


def _write_with(name: str, plan: Plan, settings: dict, recent_titles: list[str],
                pictures: list[tuple[str, str]]) -> S.Script:
    provider = _provider(name)
    backups = settings["models"].get(f"{name}_text_fallback") or []
    models = [settings["models"][f"{name}_text"], *([backups] if isinstance(backups, str) else backups)]
    model = models[0]
    system, user = S.build_prompt(plan, settings, recent_titles, pictures)
    ids = [pid for pid, _ in pictures]
    out_schema = S.schema(ids)

    feedback, drafts = "", 0
    # Content attempts (drafts) and outages are counted separately: switching to a backup model
    # because one is overloaded never uses up a chance to fix the script.
    while drafts < MAX_DRAFTS:
        log.info("  writing script with %s (%s), draft %d", name, model, drafts + 1)
        try:
            data = S.tidy(provider.complete_json(model, system, user + feedback, out_schema))
            problems = S.validate(data, settings, ids)
            if not problems:
                chosen = dict(pictures).get(data["image_id"], "")
                review = provider.complete_json(
                    model, S.REVIEW_SYSTEM,
                    json.dumps(data, ensure_ascii=False, indent=1) + f"\n\nChosen picture: {chosen}", S.REVIEW_SCHEMA)
        except (ProviderError, json.JSONDecodeError) as e:
            log.warning("  %s failed: %s", model, str(e).splitlines()[0][:200])
            if model == models[-1]:
                raise  # every model of this provider is unavailable: the caller tries the next provider
            model = models[models.index(model) + 1]
            log.info("  switching to fallback model %s", model)
            continue

        drafts += 1
        if problems:
            log.warning("  draft rejected: %s", "; ".join(problems))
            feedback = ("\n\nYour previous answer had these problems; fix all of them:\n- " + "\n- ".join(problems)
                        + "\nPrevious answer:\n" + json.dumps(data, ensure_ascii=False))
            continue
        if review.get("ok"):
            result = S.to_script(data, f"{name}:{model}")
            result.review_issues = review.get("issues", [])
            return result
        issues = review.get("issues") or ["reviewer rejected the script"]
        log.warning("  review rejected the draft: %s", "; ".join(issues))
        feedback = ("\n\nAn editor rejected your previous answer for these reasons; write a new version that fixes them:\n- "
                    + "\n- ".join(issues) + "\nPrevious answer:\n" + json.dumps(data, ensure_ascii=False))

    raise NoPublishableScript(f"No script passed checks and review after {MAX_DRAFTS} drafts -- "
                              "nothing was made or uploaded.")
