"""Spawner (the port in contracts/ports.py) on real processes: the one way app/ and cli/ start a child.
Every child's environment is built by `childenv.tool_env` (an allowlist of names, no virtualenv); a child that outlives the call
is spawned through stream-proc's held spawn (adapters/procs.py), in a session of its own."""
import subprocess
import threading
from collections.abc import Callable, Mapping
from typing import IO, Literal

from taskloop.adapters import procs
from taskloop.adapters.childenv import tool_env
from taskloop.contracts.env import Env
from taskloop.contracts.ports import Hold, Ran, RanBytes, Streamed, WaitTimeout

GRACE_S = procs.STOP_GRACE_S


class Started:
    """A running `Popen` as the port's `Child`: a timed-out wait is WaitTimeout, a stop goes through stream-proc."""

    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self.popen = popen
        self.pid = popen.pid
        self.stdin: IO[bytes] | None = popen.stdin

    def poll(self) -> int | None:
        return self.popen.poll()

    def wait(self, timeout: float | None = None) -> int:
        try:
            return self.popen.wait(timeout)
        except subprocess.TimeoutExpired as e:
            raise WaitTimeout(str(timeout)) from e

    def stop(self, grace: float) -> None:
        procs.stop_tree(self.popen, grace=grace)

    def stop_async(self, grace: float) -> None:
        procs.stop_in_thread(self.popen, grace)


def _stdio(stdin: str, out: IO[bytes] | str) -> dict[str, object]:
    kw: dict[str, object] = {"stdin": subprocess.PIPE if stdin == "pipe" else subprocess.DEVNULL}
    if out == "null":
        kw.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif out != "inherit":
        kw.update(stdout=out, stderr=subprocess.STDOUT)
    return kw


class RealSpawner:
    def __init__(self, env: Env) -> None:
        self.env = env  # what every child inherits (through the allowlist), unless a call brings its own base

    def _env(self, env: Mapping[str, str] | None, extra: Mapping[str, str] | None) -> dict[str, str]:
        return tool_env(self.env.vars if env is None else env, extra)

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None, capture: bool = True, input: str | None = None) -> Ran:
        try:
            r = subprocess.run(argv, cwd=cwd, env=self._env(env, extra), capture_output=capture, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout_s, check=False, input=input)
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return Ran(exit=124, out=out, timed_out=True)
        return Ran(exit=r.returncode, out=r.stdout or "", err=r.stderr or "")

    def run_bytes(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None) -> RanBytes:
        r = subprocess.run(argv, cwd=cwd, env=self._env(None, extra), capture_output=True, check=False)
        return RanBytes(exit=r.returncode, out=r.stdout or b"", err=r.stderr or b"")

    def stream(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
               extra: Mapping[str, str] | None = None,
               on_output: Callable[[str], None], timeout_s: float | None = None, stop: threading.Event | None = None,
               grace: float = procs.STOP_GRACE_S) -> Streamed:
        res = procs.stream(argv, cwd=cwd, env=self._env(env, extra), on_output=on_output, timeout_s=timeout_s, stop=stop, grace=grace)
        return Streamed(returncode=res.returncode, signal=res.signal, timed_out=res.timed_out, secs=res.secs,
                        survivors=tuple(res.survivors))

    def start(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              extra: Mapping[str, str] | None = None, stdin: Literal["null", "pipe"] = "null",
              out: IO[bytes] | Literal["null", "inherit"] = "null") -> Started:
        return Started(procs.spawn(argv, cwd=cwd, env=self._env(env, extra), close_fds=True, **_stdio(stdin, out)))

    def start_held(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
                   extra: Mapping[str, str] | None = None, out: IO[bytes]) -> tuple[Started, Hold]:
        p, hold = procs.popen_held(argv, cwd=cwd, env=self._env(env, extra), start_new_session=True, **_stdio("null", out))
        return Started(p), hold

    def stop_pid(self, pid: int, start: str | None = None, grace: float = GRACE_S) -> tuple[int, ...]:
        return procs.stop_pid(pid, start, grace)
