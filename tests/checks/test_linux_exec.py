"""A check with `in: linux` runs by git push to the executor and ssh: exit code and artifacts come back, a down executor fails loudly."""
import io
import shlex
import tarfile
import threading
from collections.abc import Callable
from pathlib import Path

import msgspec
import pytest

from taskloop.app.checks.linux import EXECUTOR_DOWN_RC, LinuxRun
from taskloop.contracts.config import CheckSpec, ExecutorConfig
from taskloop.contracts.ids import CheckId
from taskloop.contracts.ports import Ran, RanBytes, Streamed
from taskloop.contracts.slots import SlotGitError

CFG = ExecutorConfig(host="pix", root="tl")


class FakeGit:
    def __init__(self, down: bool = False) -> None:
        self.pushed: list[tuple[str, str, str]] = []
        self.down = down

    def push(self, d: str, remote: str, refspec: str) -> None:
        if self.down:
            raise SlotGitError("ssh: connect to host pix port 22: Connection refused")
        self.pushed.append((d, remote, refspec))


class FakeSpawner:
    """Records every argv; the executor answers `rc` and the tar of `files` for the artifact fetch."""

    def __init__(self, rc: int = 0, files: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.rc, self.files = rc, files or {}

    def run(self, argv: list[str], *, timeout_s: float | None = None) -> Ran:
        self.calls.append(argv)
        return Ran(exit=0, out="/home/x\n")

    def run_bytes(self, argv: list[str]) -> RanBytes:
        self.calls.append(argv)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name, text in self.files.items():
                data = text.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return RanBytes(exit=0, out=buf.getvalue())

    def stream(self, argv: list[str], *, on_output: Callable[[str], None], timeout_s: float | None = None,
               stop: threading.Event | None = None) -> Streamed:
        self.calls.append(argv)
        on_output("remote says hi\n")
        return Streamed(returncode=self.rc, signal=None, timed_out=None, secs=0.1)


def run_linux(tmp: Path, git: FakeGit, sp: FakeSpawner) -> tuple[int, str]:
    art = tmp / "art"
    art.mkdir()
    return LinuxRun(CFG, git, sp).run(
        wt=str(tmp), repo="repo-1", slot="s1", sha="abc123", run_id="r9", step=CheckId("lint"), argv=["just", "lint"],
        env={"X": "1"}, log=tmp / "log", artifact_dir=art, timeout_s=60)


class TestLinux:
    def test_the_committed_commit_is_pushed_to_the_run_ref_of_the_bare_repo(self, workdir):
        git, sp = FakeGit(), FakeSpawner()
        run_linux(workdir, git, sp)
        assert git.pushed == [(str(workdir), "pix:/home/x/tl/repo-1.git", "abc123:refs/tl/r9")]

    def test_the_argv_runs_on_the_executor_in_the_slots_worktree_and_its_exit_and_output_come_back(self, workdir):
        sp = FakeSpawner(rc=3)
        rc, tail = run_linux(workdir, FakeGit(), sp)
        assert rc == 3
        assert "remote says hi" in tail
        assert "remote says hi" in (workdir / "log").read_text()
        ssh = next(c for c in sp.calls if "just" in " ".join(c))
        assert ssh[0] == "ssh" and "pix" in ssh
        assert shlex.split(ssh[-1]) == ["env", "-C", "/home/x/tl/repo-1/s1", "TL_ARTIFACT_DIR=/home/x/tl/repo-1/.artifacts/r9-lint",
                                        "X=1", "just", "lint"]

    def test_the_executors_artifacts_land_in_the_local_artifact_dir(self, workdir):
        run_linux(workdir, FakeGit(), FakeSpawner(files={"out/report.txt": "ok"}))
        assert (workdir / "art" / "out" / "report.txt").read_text() == "ok"

    def test_a_down_executor_fails_loudly_and_nothing_runs_locally(self, workdir):
        sp = FakeSpawner()
        rc, tail = run_linux(workdir, FakeGit(down=True), sp)
        assert rc == EXECUTOR_DOWN_RC
        assert "executor pix is down" in tail and "Connection refused" in tail
        assert not any("just" in " ".join(c) for c in sp.calls)


@pytest.mark.parametrize(("spec", "where"), [({}, "host"), ({"in": "linux"}, "linux")])
def test_a_check_names_its_location_with_in(spec, where):
    assert msgspec.convert({"id": "t", "argv": ["true"], **spec}, CheckSpec).where == where
