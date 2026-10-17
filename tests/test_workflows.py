"""The cloud pipelines: every file is valid, every expression is a real one, every pipeline calls
shared steps that exist with the inputs they need, and each has its own name and pause key."""
import glob
import os
import re

import yaml

W = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows")


def _all():
    return {os.path.basename(f): (open(f, encoding="utf-8").read(), yaml.safe_load(open(f, encoding="utf-8")))
            for f in glob.glob(os.path.join(W, "*.yml"))}


def test_every_expression_starts_with_a_dollar():
    for name, (text, _) in _all().items():
        bad = [text[m.start():m.start() + 30] for m in re.finditer(r"(?<!\$)\{\{", text)]
        assert not bad, f"{name}: {bad}"


def test_pipelines_call_existing_shared_steps_with_their_inputs():
    files = _all()
    for name, (_, d) in files.items():
        for job in (d.get("jobs") or {}).values():
            uses = job.get("uses", "")
            if not uses.startswith("./"):
                continue
            called = files[os.path.basename(uses)][1]
            inputs = called[True]["workflow_call"]["inputs"]
            given = job.get("with", {})
            assert all(k in given for k, spec in inputs.items() if spec.get("required")), name
            assert all(k in inputs for k in given), name
            assert job.get("secrets") == "inherit", name


def test_every_pipeline_has_its_own_name_and_pause_key():
    from autopilot.pause import PIPELINES

    names, keys = [], []
    for name, (_, d) in _all().items():
        if name.startswith(("short-", "story-")):
            names.append(d["name"])
            key = next(iter(d["jobs"].values()))["with"]["pipeline"]
            keys.append(key)
            assert key == name[:-4] and key in PIPELINES, name
    assert len(set(names)) == len(names) and len(set(keys)) == len(keys)
