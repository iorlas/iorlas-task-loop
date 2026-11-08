"""Live: committed checks, persistent slots and cancellation on a real Linux executor.

Runs only through `just test-live`; a person runs it with TL_LIVE_EXECUTOR_HOST
(an ssh destination) and optionally TL_LIVE_EXECUTOR_ROOT (default: tl-live).
No ssh or local repository setup happens unless the host is configured.
"""

import os
import shlex
import threading
import time
import uuid

import pytest
from support.spawn import port_git, real_spawner

from tlgate.linux import EXECUTOR_DOWN_RC, LinuxRun
from tlkernel.config import ExecutorConfig
from tlkernel.ids import CheckId
from tltestkit.checked import run_checked


@pytest.fixture
def executor(tmp_path):
    host = os.environ.get("TL_LIVE_EXECUTOR_HOST")
    if not host:
        pytest.skip("TL_LIVE_EXECUTOR_HOST is not set; a person must configure a real Linux executor")
    root = os.environ.get("TL_LIVE_EXECUTOR_ROOT", "tl-live")
    namespace = f"live-{uuid.uuid4().hex}"
    cfg = ExecutorConfig(host=host, root=root)
    spawner = real_spawner()
    # Nest the repo so its bare sibling and worktrees share one disposable path.
    repo_name = f"{namespace}/repo"
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        run_checked(["git", *args], repo)
    (repo / "hello.txt").write_text("committed\n")
    (repo / ".gitignore").write_text("slot-cache\npid\n")
    run_checked(["git", "add", "hello.txt", ".gitignore"], repo)
    run_checked(["git", "commit", "-qm", "init"], repo)
    git = port_git()
    runner = LinuxRun(cfg, git, spawner)
    try:
        yield runner, repo, repo_name, git.rev_parse(str(repo), "HEAD")
    finally:
        # One UUID-owned path only; also removes the bare repo at namespace/repo.git.
        command = shlex.join(["rm", "-rf", "--", f"{root}/{namespace}"])
        done = spawner.run([*cfg.ssh, host, command], timeout_s=15)
        assert done.exit == 0, done.err or done.out


def run_check(executor, tmp_path, argv, *, slot="one", stop=None):
    runner, repo, name, sha = executor
    attempt = uuid.uuid4().hex
    artifacts = tmp_path / attempt
    artifacts.mkdir()
    done = runner.run(
        wt=str(repo), repo=name, slot=slot, sha=sha, run_id=attempt,
        step=CheckId("live"), argv=argv, env={}, log=tmp_path / f"{attempt}.log",
        artifact_dir=artifacts, timeout_s=60, stop=stop,
    )
    return done, artifacts, tmp_path / f"{attempt}.log"


def test_committed_tree_artifacts_and_persistent_slots(executor, tmp_path):
    # Given: a committed tree and an uncommitted file that must never reach the executor.
    _, repo, _, _ = executor
    (repo / "dirty.txt").write_text("local only\n")
    # When: a check reads the commit, writes an artifact and leaves an ignored cache.
    script = ('cat hello.txt; test ! -e dirty.txt || exit 9; '
              'echo kept > "$TL_ARTIFACT_DIR/out.txt"; echo cached > slot-cache; exit 7')
    done, artifacts, _ = run_check(executor, tmp_path, ["sh", "-c", script])
    # Then: output, exit status and artifacts come back, with persistence confined to a slot.
    assert done.rc == 7, done.tail
    assert "committed" in done.tail
    assert (artifacts / "out.txt").read_text() == "kept\n"
    again, _, _ = run_check(executor, tmp_path, ["sh", "-c", "test -f slot-cache && cat slot-cache"])
    assert again.rc == 0 and "cached" in again.tail, again.tail
    other, _, _ = run_check(executor, tmp_path, ["sh", "-c", "test ! -e slot-cache"], slot="two")
    assert other.rc == 0, other.tail


def test_unreachable_executor_never_runs_locally(executor, tmp_path):
    # Given: an unreachable host with a bounded connection attempt.
    _, repo, name, sha = executor
    cfg = ExecutorConfig(host="tl-live-no-such-host.invalid", ssh=["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3"])
    runner = LinuxRun(cfg, port_git(), real_spawner())
    marker = tmp_path / "must-not-run"
    # When: the remote check would create an absolute local marker if executed here.
    done, _, log = run_check((runner, repo, name, sha), tmp_path, ["touch", str(marker)])
    # Then: the executor-down result and log are explicit, and nothing ran locally.
    assert done.rc == EXECUTOR_DOWN_RC, done.tail
    assert f"executor {cfg.host} is down" in log.read_text()
    assert not marker.exists()


def test_cancel_removes_remote_processes(executor, tmp_path):
    # Given: a shell and a descendant, both with a unique searchable token in their argv.
    runner, _, _, _ = executor
    token = f"tl-live-token-{uuid.uuid4().hex}"
    stop = threading.Event()
    finished = threading.Event()

    def cancel():
        if not finished.wait(2):
            stop.set()

    thread = threading.Thread(target=cancel)
    thread.start()
    # When: another thread stops the check after about two seconds.
    try:
        done, _, _ = run_check(executor, tmp_path, ["sh", "-c", 'sh -c "sleep 300 # $0" & wait', f"TOKEN={token}"], stop=stop)
    finally:
        finished.set()
        thread.join()
    # Then: cancellation is reported and neither the shell nor its descendant survives within 15 seconds.
    assert done.stopped, done.tail
    deadline = time.monotonic() + 15
    pattern = f"[t]{token[1:]}"  # pgrep's own argv contains the brackets, never the literal token.
    command = shlex.join(["pgrep", "-f", pattern])
    while True:
        found = runner.spawner.run([*runner.cfg.ssh, runner.cfg.host, command], timeout_s=3)
        if found.exit == 1:
            break
        assert found.exit == 0, found.err or found.out
        assert time.monotonic() < deadline, f"remote processes survived cancellation: {found.out}"
        threading.Event().wait(0.5)
