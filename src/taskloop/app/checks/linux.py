"""A check with `in: linux`: the committed commit goes to a bare repo on the executor by `git push` over ssh (refs/tl/<run>), the
executor keeps one persistent worktree per slot at <root>/<repo>/<slot>, the argv runs there, and its exit code, output and
TL_ARTIFACT_DIR come back. A down executor fails the check loudly: there is no run on this machine instead.

Every remote step is one plain argv (no shell on either side); the Linux executor's `env -C` is the change of directory.
"""
# git-port-exempt: the git argvs below run on the executor over ssh, on its own repos; the local push goes through the Git port
import hashlib
import io
import shlex
import tarfile
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

from taskloop.contracts.config import ExecutorConfig
from taskloop.contracts.ids import CheckId
from taskloop.contracts.ports import Ran, RanBytes, Streamed
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.checks.matchers import safe_name

EXECUTOR_DOWN_RC = 255  # ssh's own code for "could not connect": the check did not run
TAIL_LINES = 40
WALL_RC = 124
SETUP_S = 1800  # the executor's setup (uv sync, mise install) may take this long
SETUP_FAILED_RC = 1
STEP_S = 120  # a prepare step (probe, init, checkout) that takes longer means the executor is not answering


class ExecutorDown(Exception):
    """A step before the check began failed: `why` is what the executor or ssh said."""


class Remote(NamedTuple):
    """How the run ended: the exit code, the last lines of output, and whether the engine
    stopped it (a cancelled lane) or its wall limit did."""

    rc: int
    tail: str
    stopped: bool = False
    wall_hit: bool = False


class SetupFailed(Exception):
    """The slot's setup on the executor exited non-zero: the check is red, its text is the setup's output."""


class Pusher(Protocol):
    """The part of the Git port this uses: a plain push (never forced)."""

    def push(self, d: str, remote: str, refspec: str) -> None: ...
    def rev_parse(self, d: str, rev: str) -> str: ...


class Ssh(Protocol):
    """The part of the Spawner this uses."""

    def run(self, argv: list[str], *, timeout_s: float | None = ...) -> Ran: ...
    def run_bytes(self, argv: list[str]) -> RanBytes: ...
    def stream(self, argv: list[str], *, on_output: Callable[[str], None], timeout_s: float | None = ...,
               stop: threading.Event | None = ...) -> Streamed: ...


class LinuxRun:
    def __init__(self, cfg: ExecutorConfig, git: Pusher, spawner: Ssh) -> None:
        self.cfg, self.git, self.spawner = cfg, git, spawner

    def run(self, *, wt: str, repo: str, slot: str, sha: str, run_id: str, step: CheckId, argv: list[str], env: dict[str, str],
            log: Path, artifact_dir: Path, timeout_s: float, stop: threading.Event | None = None) -> Remote:
        """How it ended; the whole output goes to `log`."""
        attempt = f"{run_id}-{safe_name(step)}"
        remote_art = ""
        try:
            home = self._prepare(wt, repo, slot, sha, run_id)
            remote_art = f"{home}/{self.cfg.root}/{repo}/.artifacts/{attempt}"
            self._must(["mkdir", "-p", remote_art])
        except SetupFailed as err:
            log.write_text(f"{err}\n", encoding="utf-8")
            return Remote(SETUP_FAILED_RC, str(err))
        except ExecutorDown as err:
            text = (f"check could not run: executor {self.cfg.host or '(none configured)'} is down: {err}\n"
                    "(a `in: linux` check never runs here instead)")
            log.write_text(text + "\n", encoding="utf-8")
            return Remote(EXECUTOR_DOWN_RC, text)
        tail: deque[str] = deque(maxlen=TAIL_LINES)
        with open(log, "w", encoding="utf-8") as out:
            def on_output(line: str) -> None:
                line = line.replace("\r", "")  # the pty of `ssh -tt` ends lines with CRLF
                out.write(line)
                tail.extend(line.splitlines())
            work = f"{home}/{self.cfg.root}/{repo}/{slot}"
            # -tt: a pty, so the executor hangs the run up when this ssh is killed (a cancelled lane, the wall limit)
            done = self.spawner.stream(self._ssh(["env", "-C", work, f"TL_ARTIFACT_DIR={remote_art}",
                                                  *[f"{k}={v}" for k, v in env.items()], *argv], tty=True),
                                       on_output=on_output, timeout_s=timeout_s, stop=stop)
        rc = WALL_RC if done.timed_out == "wall" else done.returncode if done.returncode is not None else -(done.signal or 1)
        return Remote(rc, "\n".join(tail) + self._fetch(remote_art, artifact_dir), stopped=done.timed_out == "stopped",
                      wall_hit=done.timed_out == "wall")

    def _prepare(self, wt: str, repo: str, slot: str, sha: str, run_id: str) -> str:
        """The commit is on the executor and checked out in the slot's worktree; the executor's home directory."""
        cfg = self.cfg
        if not cfg.host:
            raise ExecutorDown("engine.executor.host is not set")
        home = self._must(["pwd"]).strip()  # also the probe: an executor that does not answer ends here
        bare, work = f"{home}/{cfg.root}/{repo}.git", f"{home}/{cfg.root}/{repo}/{slot}"
        self._must(["git", "init", "--bare", "-q", bare])
        try:
            self.git.push(wt, f"{cfg.host}:{bare}", f"{sha}:refs/tl/{run_id}")
        except SlotGitError as err:
            raise ExecutorDown(str(err)) from err
        if self._ssh_run(["test", "-d", work]).exit == 0:  # the slot's worktree stays between runs: its caches are the speed
            self._must(["git", "-C", work, "checkout", "-q", "--detach", "-f", sha])
            self._must(["git", "-C", work, "clean", "-qfd"])
        else:
            self._must(["git", "-C", bare, "worktree", "add", "-q", "--detach", work, sha])
        self._setup(wt, sha, work, f"{home}/{cfg.root}/{repo}/.setup")
        return home

    def _setup(self, wt: str, sha: str, work: str, marks: str) -> None:
        """The profile's setup in the slot's worktree, again only when its inputs or command changed: a marker file names the state."""
        cfg = self.cfg
        if not cfg.setup:
            return
        state = hashlib.sha256()
        state.update("\0".join(cfg.setup).encode())
        for path in cfg.setup_inputs:
            state.update(f"\0{path}={self.git.rev_parse(wt, f'{sha}:{path}')}".encode())
        mark = f"{marks}/{Path(work).name}-{state.hexdigest()[:20]}"
        if self._ssh_run(["test", "-e", mark]).exit == 0:
            return
        done = self.spawner.run(self._ssh(["env", "-C", work, *cfg.setup]), timeout_s=SETUP_S)
        if done.exit != 0:
            raise SetupFailed(f"setup {' '.join(cfg.setup)} exited {done.exit} on executor {cfg.host}:\n"
                              + "\n".join((done.out + done.err).strip().splitlines()[-TAIL_LINES:]))
        self._must(["mkdir", "-p", marks])
        self._must(["touch", mark])

    def _ssh(self, argv: list[str], tty: bool = False) -> list[str]:
        # ssh hands the remote one string: quoted so it splits back to argv
        return [*self.cfg.ssh, *(["-tt"] if tty else []), self.cfg.host, shlex.join(argv)]

    def _ssh_run(self, argv: list[str]) -> Ran:
        return self.spawner.run(self._ssh(argv), timeout_s=STEP_S)

    def _must(self, argv: list[str]) -> str:
        done = self._ssh_run(argv)
        if done.exit != 0:
            raise ExecutorDown((done.err or done.out).strip() or f"`{argv[0]}` exit {done.exit}")
        return done.out

    def _fetch(self, remote: str, artifact_dir: Path) -> str:
        """The executor's TL_ARTIFACT_DIR into the local one; a failure is said in the tail, the check's exit code stands."""
        got = self.spawner.run_bytes(self._ssh(["tar", "-C", remote, "-cf", "-", "."]))
        if got.exit != 0:
            return f"\n(artifacts not fetched: {got.err.decode(errors='replace').strip()})"
        with tarfile.open(fileobj=io.BytesIO(got.out)) as tar:
            tar.extractall(artifact_dir, filter="data")
        return ""
