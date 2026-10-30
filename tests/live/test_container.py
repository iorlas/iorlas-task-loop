"""Scenario 2: a check in a container through real docker (container_run.py, the runner the engine starts). Skipped with its reason when
no docker daemon answers, or when the image is not there (set TL_LIVE_IMAGE; the default is alpine:3)."""
import os
import subprocess
import sys

import pytest

from taskloop.adapters.spawner import RealSpawner
from taskloop.app.checks import container

IMAGE = os.environ.get("TL_LIVE_IMAGE", "alpine:3")


@pytest.fixture
def docker_image():
    if not container.docker_ok(RealSpawner()):
        pytest.skip("no docker daemon answers `docker info` (this host has none)")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, check=False).returncode:
        pytest.skip(f"image {IMAGE} is not on this docker; pull it or set TL_LIVE_IMAGE")
    return IMAGE


def test_given_a_worktree_when_a_check_runs_in_a_container_then_it_sees_the_files_and_returns_artifacts(world, tmp_path, docker_image):
    # Given: a git worktree with f.txt, and an artifacts folder
    wt, art = tmp_path / "wt", tmp_path / "art"
    wt.mkdir()
    art.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "f.txt").write_text("f\n")
    # When: the runner runs a check that needs f.txt and writes an artifact
    runner = container.RUNNER
    cmd = [sys.executable, str(runner), "--image", docker_image, "--name", "tl-live-check", "--art", str(art), "--",
           "sh", "-c", 'test -f f.txt && echo seen > "$TL_ARTIFACTS/seen.txt"']
    r = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=600, check=False)
    # Then: it exits 0 and the artifact came back to the host
    assert r.returncode == 0, r.stdout + r.stderr
    assert (art / "seen.txt").read_text().strip() == "seen"
