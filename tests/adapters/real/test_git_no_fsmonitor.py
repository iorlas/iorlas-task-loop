"""A repo's own `core.fsmonitor` is a program git runs on every status: the port never runs it (tl-7i9k.53, M-066)."""

import os
import subprocess
from pathlib import Path

from support.tmpdir import TemporaryDirectory

from taskloop.adapters.git import RealGit
from tlkernel.env import Env, snapshot


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=str(cwd), check=True, capture_output=True, text=True)


def test_the_port_reads_status_without_running_the_repos_fsmonitor_program():
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(os.path.realpath(tmp))
        repo, marker, hook = root / "r", root / "ran", root / "mon.sh"
        repo.mkdir()
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b"], ["config", "user.name", "n"]):
            sh("git", *a, cwd=repo)
        (repo / "f").write_text("1")
        sh("git", "add", "f", cwd=repo)
        sh("git", "commit", "-q", "-m", "one", cwd=repo)
        hook.write_text(f"#!/bin/sh\necho ran > {marker}\nexit 1\n")
        hook.chmod(0o755)
        sh("git", "config", "core.fsmonitor", str(hook), cwd=repo)
        subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), check=False, capture_output=True)
        assert marker.exists(), "precondition: this git runs core.fsmonitor on status"
        marker.unlink()
        port = RealGit(Env({k: v for k, v in snapshot().vars.items() if k != "TL_LAND"}))
        assert port.dirty(str(repo)) is False
        assert not marker.exists()
