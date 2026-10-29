"""A docker for tests that is not a process: the calls the engine and container_run.py make (`docker_ok`, `_docker`, `docker()` and the
`docker run` spawn) go to a recorder. `run` unpacks the tar the runner sends into a sandbox dir that stands for the container's disk
(TMPDIR) and answers the check's argv through procsim (so the check is a fake too), so a check's result is real. No docker, no daemon."""
import io
import os
import shlex
import subprocess
import tarfile
from pathlib import Path
from unittest import mock

from support import procsim

from taskloop.app.checks import container, container_run


class _Stdin(io.BytesIO):
    def close(self) -> None:  # the bytes outlive the close: the "container" reads them after the runner is done writing
        pass


class _Run:
    """The `docker run` client as the runner sees it: stdin takes the tar; `wait` is the check running in the sandbox."""

    def __init__(self, dock: "FakeDocker", cmd: list[str]) -> None:
        self.dock, self.cmd = dock, cmd
        self.stdin = _Stdin()
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return 137 if self.dock.killed else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = self.dock.execute(self.cmd, self.stdin.getvalue())
        return self.returncode


class FakeDocker:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.up = True
        self.calls: list[list[str]] = []
        self.output = ""
        self.on_wait = None  # called inside `wait` of a run: a signal that arrives while the runner waits
        self.killed: set[str] = set()

    def install(self, test) -> None:
        for target, name, fn in ((container, "docker_ok", self.docker_ok), (container, "_docker", self.docker_rc),
                                 (container_run, "docker", self.docker)):
            p = mock.patch.object(target, name, fn)
            p.start()
            test.addCleanup(p.stop)
        spawn = mock.patch.object(container_run.procs, "spawn", lambda cmd, **kw: _Run(self, cmd))
        spawn.start()
        test.addCleanup(spawn.stop)
        # the engine runs the runner as a command: here it is the runner's main, in process
        text = shlex.join([container.sys.executable, str(container.RUNNER)])
        procsim.fake(text, self._runner, args=True)

    def _runner(self, cwd: Path, env) -> tuple[int, str]:
        self.output = ""
        before = os.getcwd()
        os.chdir(cwd)
        try:
            return container_run.main(list(procsim.argv()[2:])), self.output
        finally:
            os.chdir(before)

    def verbs(self) -> list[str]:
        return [c[0] for c in self.calls]

    def down(self) -> None:
        self.up = False

    def docker_ok(self) -> bool:
        self.calls.append(["info"])
        return self.up

    def docker_rc(self, *args: str) -> int:
        self.calls.append(list(args))
        return 0

    def docker(self, *args: str, **kw) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        out = b""
        if args[0] == "kill":
            self.killed.add(args[1])
        elif args[0] == "cp":
            box = self.root / args[1].split(":")[0] / "tl-art"
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                tar.add(box, arcname=".")
            out = buf.getvalue()
        return subprocess.CompletedProcess(list(args), 0, out, b"")

    def execute(self, cmd: list[str], data: bytes) -> int:
        self.calls.append(cmd[1:])
        env, name, i = dict(os.environ), "", 2
        while cmd[i].startswith("-"):
            if cmd[i] in ("--name", "-w", "-e"):
                if cmd[i] == "--name":
                    name = cmd[i + 1]
                elif cmd[i] == "-e":
                    k, _, v = cmd[i + 1].partition("=")
                    env[k] = v
                i += 1
            i += 1
        box = self.root / name
        work, art = box / "tl-w", box / "tl-art"
        for d in (work, art):
            d.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
            tar.extractall(work, filter="data")
        if self.on_wait:
            self.on_wait(name)
        if name in self.killed:
            return 137
        env.update(TMPDIR=str(box), TL_ARTIFACTS=str(art))
        done = subprocess.run(cmd[i + 5:], cwd=work / env["TL_BOX_CWD"], env=env, capture_output=True, text=True, check=False)
        self.output += done.stdout
        return done.returncode
