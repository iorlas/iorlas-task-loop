"""`in: linux` over the real git and process adapters. The executor is this machine: an `ssh` shim runs the remote command in a
local shell, so the push, the slot's persistent worktree, the exit code and the artifact fetch all happen for real."""
import os
import stat

from support.checked import run_checked
from support.spawn import port_git, real_spawner

from taskloop.app.checks.linux import LinuxRun
from taskloop.contracts.config import ExecutorConfig
from taskloop.contracts.ids import CheckId

# `ssh [-o opt]... <host> <command>`: git's own ssh call has the same shape
SHIM = '#!/bin/sh\nwhile [ "$1" = -o ]; do shift 2; done\nshift\ncd "$HOME" && exec sh -c "$1"\n'


def test_a_commit_is_pushed_run_in_the_slot_worktree_and_its_artifacts_come_back(workdir, monkeypatch):
    home, repo = workdir / "home", workdir / "repo"
    home.mkdir()
    repo.mkdir()
    (workdir / "bin").mkdir()
    shim = workdir / "bin" / "ssh"
    shim.write_text(SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{shim.parent}:{os.environ['PATH']}")  # git's own `ssh` is the shim
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        run_checked(["git", *args], repo)
    (repo / "hello.txt").write_text("committed\n")
    (repo / "dirty.txt").write_text("never committed\n")
    (repo / ".gitignore").write_text("setup-ran\n")  # setup output is ignored: `git clean -fd` keeps it between runs
    run_checked(["git", "add", "hello.txt", ".gitignore"], repo)
    run_checked(["git", "commit", "-qm", "init"], repo)
    sha = port_git().rev_parse(str(repo), "HEAD")
    runner = LinuxRun(ExecutorConfig(host="exec", root="tl", ssh=[str(shim)], setup=["touch", "setup-ran"],
                                              setup_inputs=["hello.txt"]), port_git(), real_spawner())
    script = ["sh", "-c", 'cat hello.txt; test ! -e dirty.txt; echo $TL_ARTIFACT_DIR; echo kept > "$TL_ARTIFACT_DIR/out.txt"; exit 7']
    for _ in range(2):  # the second run reuses the slot's worktree
        art = workdir / "art"
        art.mkdir(exist_ok=True)
        rc, tail = runner.run(wt=str(repo), repo="r", slot="s1", sha=sha, run_id="r1", step=CheckId("t"), argv=script, env={},
                              log=workdir / "log", artifact_dir=art, timeout_s=60)
        assert rc == 7 and "committed" in tail, tail
        assert (art / "out.txt").read_text() == "kept\n"
    assert (home / "tl" / "r" / "s1" / "setup-ran").is_file()  # the slot's setup ran in its worktree before the check
    assert len(list((home / "tl" / "r" / ".setup").glob("s1-*"))) == 1  # ... once: the second run found its marker
    assert (home / "tl" / "r" / "s1" / "hello.txt").is_file()
    assert (home / "tl" / "r.git" / "refs" / "tl" / "r1").is_file()
