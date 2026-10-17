"""Daily health check of everything the pipelines depend on, BEFORE a pipeline needs it.

Each check prints one line; a failure is reported as a GitHub error (GitHub then emails you) with what
to do about it. Nothing is made or uploaded. Needs only the Python standard library.
Reads the secrets from environment variables (set by .github/workflows/health.yml)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

CHANNELS = {"YT_TOKEN_JSON": ("UCZcyzGOG0qFhVBlemfhs_Sw", "BrahmaNadagam", "youtube_sign_in.bat"),
            "YT_TOKEN_KIDS_JSON": ("UCfKL9kT6cpKr4E9puFXAJMQ", "the kids' channel", "story_kids_sign_in.bat")}
failures, warnings = [], []


def http(url: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, dict(r.headers), r.read()


def ok(what: str):
    print(f"OK    {what}")


def fail(what: str, todo: str):
    failures.append(what)
    print(f"::error title={what}::{todo}")


def warn(what: str, todo: str):
    warnings.append(what)
    print(f"::warning title={what}::{todo}")


def youtube(secret: str, channel_id: str, name: str, bat: str):
    raw = os.environ.get(secret, "")
    if not raw:
        return fail(f"{name}: no sign-in", f"The {secret} secret is empty. Run {bat} on the laptop and paste the token file into it.")
    try:
        tok = json.loads(raw)
        body = urllib.parse.urlencode({"client_id": tok["client_id"], "client_secret": tok["client_secret"],
                                       "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}).encode()
        _, _, out = http("https://oauth2.googleapis.com/token", body)
        access = json.loads(out)["access_token"]
        _, _, out = http("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                         headers={"Authorization": f"Bearer {access}"})
        items = json.loads(out).get("items", [])
        if not items or items[0]["id"] != channel_id:
            return fail(f"{name}: wrong channel", f"The {secret} sign-in is for another channel. Run {bat} again and choose {name}.")
        ok(f"{name}: YouTube sign-in works ({items[0]['snippet']['title']})")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        if "invalid_grant" in text:
            fail(f"{name}: YouTube sign-in EXPIRED", f"Run {bat} on the laptop, then paste the new token file into the {secret} secret on GitHub.")
        else:
            fail(f"{name}: YouTube check failed", f"HTTP {e.code}: {text[:200]}")
    except (KeyError, ValueError) as e:
        fail(f"{name}: sign-in unreadable", f"The {secret} secret is not a valid token file ({e}). Paste the whole file again.")


def gemini(secret: str, what: str, required: bool):
    key = os.environ.get(secret, "")
    if not key:
        return (fail if required else warn)(f"{what}: no key", f"The {secret} secret is empty.")
    try:
        http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=5", headers={"x-goog-api-key": key})
        ok(f"{what}: Gemini key works")
    except urllib.error.HTTPError as e:
        fail(f"{what}: Gemini key rejected", f"HTTP {e.code}: make a new key at aistudio.google.com and put it in the {secret} secret.")


def huggingface():
    tok = os.environ.get("HF_TOKEN", "")
    if not tok:
        return warn("Hugging Face: no token", "The HF_TOKEN secret is empty: the Mahaperiyava voice needs it.")
    try:
        _, _, out = http("https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {tok}"})
        ok(f"Hugging Face token works ({json.loads(out).get('name')})")
    except urllib.error.HTTPError as e:
        fail("Hugging Face token rejected", f"HTTP {e.code}: make a new read token at huggingface.co/settings/tokens and put it in HF_TOKEN.")


def kaggle():
    tok = os.environ.get("KAGGLE_ACCESS_TOKEN", "").strip()
    if not tok:
        return fail("Kaggle: no token", "The KAGGLE_ACCESS_TOKEN secret is empty: talking faces and pictures need it.")
    try:
        # the status of one of your own private notebooks: only your token can see it
        http("https://www.kaggle.com/api/v1/kernels/status?userName=mythsiksha&kernelSlug=murugan-talking",
             headers={"Authorization": f"Bearer {tok}"})
        ok("Kaggle token works")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            fail("Kaggle token rejected", "Make a new API token at kaggle.com/settings and put it in KAGGLE_ACCESS_TOKEN.")
        else:
            warn("Kaggle check inconclusive", f"HTTP {e.code} (Kaggle may be busy); the pipelines will try anyway.")


def assets_token():
    tok = os.environ.get("ASSETS_TOKEN", "")
    if not tok:
        return fail("GitHub: no ASSETS_TOKEN", "The pipelines can't read the private files without it.")
    try:
        _, headers, _ = http("https://api.github.com/user", headers={"Authorization": f"Bearer {tok}", "User-Agent": "health"})
        exp = headers.get("github-authentication-token-expiration") or headers.get("Github-Authentication-Token-Expiration")
        if exp:
            when = datetime.strptime(exp.replace(" UTC", "").strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            days = (when - datetime.now(timezone.utc)).days
            if days < 14:
                fail("GitHub ASSETS_TOKEN expires soon", f"It expires in {days} days ({exp}). Make a new token with access to the private "
                     "files repository (github.com/settings/tokens) and put it in the ASSETS_TOKEN secret.")
            else:
                ok(f"GitHub ASSETS_TOKEN works (expires in {days} days)")
        else:
            ok("GitHub ASSETS_TOKEN works (no expiry date)")
    except urllib.error.HTTPError as e:
        fail("GitHub ASSETS_TOKEN rejected", f"HTTP {e.code}: make a new token and put it in the ASSETS_TOKEN secret.")


for secret, (cid, name, bat) in CHANNELS.items():
    youtube(secret, cid, name, bat)
gemini("GEMINI_API_KEY", "Shorts", required=True)
gemini("GEMINI_API_KEY_STORIES", "Stories", required=False)
huggingface()
kaggle()
assets_token()
print(f"\n{len(failures)} problem(s), {len(warnings)} warning(s)")
if failures:
    print("::error title=pipeline health::" + "; ".join(failures))
sys.exit(1 if failures else 0)
