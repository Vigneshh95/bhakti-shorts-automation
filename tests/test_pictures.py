from autopilot import pictures


def test_jobs_cover_every_scene_and_are_unique():
    jobs = pictures.jobs(len(pictures.SCENES) * 2, seed=5)
    assert len({j["name"] for j in jobs}) == len(jobs)
    for scene in pictures.SCENES:
        assert sum(scene in j["prompt"] for j in jobs) == 2
    assert all("looking straight at the viewer" in j["prompt"] for j in jobs)  # face for the talking step


def test_script_embeds_jobs():
    script = pictures._script(pictures.jobs(2, seed=1))
    assert "JOBS = []" not in script and "baby_murugan_" in script
