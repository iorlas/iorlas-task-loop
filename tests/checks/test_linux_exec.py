"""A check with `in: linux` runs by git push to the executor and ssh: exit code and artifacts come back, a down executor fails loudly."""
import io
import shlex
import tarfile
import threading
from collections.abc import Callable
from pathlib import Path

import msgspec
import pytest

from taskloop.app.checks.linux import EXECUTOR_DOWN_RC, LinuxRun, Remote
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

    def rev_parse(self, d: str, rev: str) -> str:
        return ""


class FakeSpawner:
    """Records every argv; the executor answers `rc` and the tar of `files` for the artifact fetch."""

    def __init__(self, rc: int = 0, files: dict[str, str] | None = None, timed_out: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.rc, self.files, self.timed_out = rc, files or {}, timed_out

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
        return Streamed(returncode=None if self.timed_out else self.rc, signal=15 if self.timed_out else None, timed_out=self.timed_out,
                        secs=0.1)


def run_linux(tmp: Path, git: FakeGit, sp: FakeSpawner) -> Remote:
    art = tmp / "art"
    art.mkdir()
    return LinuxRun(CFG, git, sp).run(
        wt=str(tmp), repo="repo-1", slot="s1", sha="abc123", run_id="r9", step=CheckId("lint"), argv=["just", "lint"],
        env={"X": "1"}, log=tmp / "log", artifact_dir=art, timeout_s=60)


class TestLinux:
    def test_the_committed_commit_is_pushed_to_the_run_ref_of_the_bare_repo(self, workdir):
        git, sp = FakeGit(), FakeSpawner()
        run_linux(workdir, git, sp)
        assert git.pushed == [(str(workdir), "pix:/home/x/tl/repo-1.git", "abc123:refs/tl/r9-lint")]

    def test_the_argv_runs_on_the_executor_in_the_slots_worktree_and_its_exit_and_output_come_back(self, workdir):
        sp = FakeSpawner(rc=3)
        rc, tail, *_ = run_linux(workdir, FakeGit(), sp)
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

    def test_the_attempts_ref_and_remote_artifacts_go_once_they_are_fetched(self, workdir):
        sp = FakeSpawner()
        run_linux(workdir, FakeGit(), sp)
        words = [shlex.split(c[-1]) for c in sp.calls]
        fetch = next(i for i, w in enumerate(words) if w[0] == "tar")
        assert words[fetch + 1:] == [["git", "-C", "tl/repo-1.git", "update-ref", "-d", "refs/tl/r9-lint"],
                                     ["rm", "-rf", "tl/repo-1/.artifacts/r9-lint"]]

    def test_artifacts_a_crashed_run_left_are_swept_when_a_week_old(self, workdir):
        sp = FakeSpawner()
        run_linux(workdir, FakeGit(), sp)
        sweep = next(w for w in (shlex.split(c[-1]) for c in sp.calls) if w[0] == "find")
        assert sweep[1] == "/home/x/tl/repo-1/.artifacts" and sweep[sweep.index("-mtime") + 1] == "+7"

    def test_the_run_has_a_pty_so_a_killed_ssh_hangs_the_remote_check_up(self, workdir):
        sp = FakeSpawner()
        run_linux(workdir, FakeGit(), sp)
        assert "-tt" in next(c for c in sp.calls if "just" in c[-1])
        assert not any("-tt" in c for c in sp.calls if "just" not in c[-1])

    @pytest.mark.parametrize(("how", "stopped", "wall"), [("stopped", True, False), ("wall", False, True), (None, False, False)])
    def test_a_run_says_whether_the_engine_stopped_it_or_its_wall_limit_did(self, workdir, how, stopped, wall):
        done = run_linux(workdir, FakeGit(), FakeSpawner(timed_out=how))
        assert (done.stopped, done.wall_hit) == (stopped, wall)

    def test_a_down_executor_fails_loudly_and_nothing_runs_locally(self, workdir):
        sp = FakeSpawner()
        rc, tail, *_ = run_linux(workdir, FakeGit(down=True), sp)
        assert rc == EXECUTOR_DOWN_RC
        assert "executor pix is down" in tail and "Connection refused" in tail
        assert not any("just" in " ".join(c) for c in sp.calls)


@pytest.mark.parametrize(("spec", "where"), [({}, "host"), ({"in": "linux"}, "linux")])
def test_a_check_names_its_location_with_in(spec, where):
    assert msgspec.convert({"id": "t", "argv": ["true"], **spec}, CheckSpec).where == where


class SetupSpawner(FakeSpawner):
    """Answers the setup marker test (`test -e`) with `marked`, and the setup argv with `setup_rc`."""

    def __init__(self, marked: bool, setup_rc: int = 0) -> None:
        super().__init__()
        self.marked, self.setup_rc = marked, setup_rc

    def run(self, argv: list[str], *, timeout_s: float | None = None) -> Ran:
        self.calls.append(argv)
        words = shlex.split(argv[-1])
        if words[:2] == ["test", "-e"]:
            return Ran(exit=0 if self.marked else 1)
        if words[:1] == ["env"] and "uv" in words:
            return Ran(exit=self.setup_rc, out="resolved 3 packages\n")
        return Ran(exit=1 if words[:2] == ["test", "-d"] else 0, out="/home/x\n")


SETUP = ExecutorConfig(host="pix", root="tl", setup=["uv", "sync", "--locked"], setup_inputs=["uv.lock"])


class RevGit(FakeGit):
    def __init__(self, lock: str) -> None:
        super().__init__()
        self.lock = lock

    def rev_parse(self, d: str, rev: str) -> str:
        return self.lock if rev == "abc123:uv.lock" else ""


def setup_calls(sp: FakeSpawner) -> list[list[str]]:
    return [shlex.split(c[-1]) for c in sp.calls if "uv" in c[-1] and shlex.split(c[-1])[0] == "env" and "just" not in c[-1]]


def run_with_setup(tmp: Path, sp: FakeSpawner, lock: str = "L1") -> Remote:
    art = tmp / "art"
    art.mkdir(exist_ok=True)
    return LinuxRun(SETUP, RevGit(lock), sp).run(
        wt=str(tmp), repo="repo-1", slot="s1", sha="abc123", run_id="r9", step=CheckId("lint"), argv=["just", "lint"], env={},
        log=tmp / "log", artifact_dir=art, timeout_s=60)


class TestSetup:
    def test_a_fresh_slot_runs_the_setup_in_its_worktree_before_the_check_and_marks_it(self, workdir):
        sp = SetupSpawner(marked=False)
        run_with_setup(workdir, sp)
        assert setup_calls(sp) == [["env", "-C", "/home/x/tl/repo-1/s1", "uv", "sync", "--locked"]]
        words = [shlex.split(c[-1]) for c in sp.calls]
        assert words.index(["env", "-C", "/home/x/tl/repo-1/s1", "uv", "sync", "--locked"]) < next(
            i for i, w in enumerate(words) if "just" in w)
        assert any(w[0] == "touch" and w[1].startswith("/home/x/tl/repo-1/.setup/s1-") for w in words)

    def test_an_unchanged_setup_does_not_run_again(self, workdir):
        sp = SetupSpawner(marked=True)
        run_with_setup(workdir, sp)
        assert setup_calls(sp) == []

    def test_the_marker_names_the_inputs_so_a_changed_lock_runs_the_setup_again(self, workdir):
        marks = []
        for lock in ("L1", "L2"):
            sp = SetupSpawner(marked=False)
            run_with_setup(workdir, sp, lock)
            marks.append(next(shlex.split(c[-1])[-1] for c in sp.calls if shlex.split(c[-1])[0] == "touch"))
        assert marks[0] != marks[1]

    def test_a_failed_setup_is_a_red_check_that_never_runs_the_argv(self, workdir):
        sp = SetupSpawner(marked=False, setup_rc=2)
        rc, tail, *_ = run_with_setup(workdir, sp)
        assert rc == 1 and "exited 2" in tail and "resolved 3 packages" in tail
        assert not any("just" in c[-1] for c in sp.calls)
