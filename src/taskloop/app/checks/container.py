"""Box: where a check that says `"in": "container"` runs. Docker reachable: in a container on a copy of the worktree on the container's
own disk (container_run.py); not reachable, or the image missing: on the host, with one warning for the round."""
import hashlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from taskloop.adapters import childenv
from taskloop.app.checks.host import CheckHost
from taskloop.contracts.checks import Check
from taskloop.contracts.ports import Spawner

RUNNER = Path(__file__).parents[2] / "adapters" / "container_run.py"
DOCKER_WAIT_S = 15
NO_DOCKER = "on host (docker not reachable)"
NO_IMAGE = "on host (container image not available)"


class Box:
    def __init__(self, host: CheckHost, spawner: Spawner) -> None:
        self.host, self.spawner = host, spawner
        self._why: str | None = None  # '' once the box is usable, else why not; asked once per round
        self._image = ""

    def plan(self, c: Check, argv: Sequence[str], env: Mapping[str, str]) -> tuple[list[str], str]:
        """(the argv to run, where it runs): the argv itself on the host, the runner's in a container."""
        if not c.container:
            return list(argv), ""
        why = self._ready()
        if why:
            return list(argv), why
        tl = {k: v for k, v in childenv.current_env().items() if k.startswith("TL_")}
        forward = {**tl, "TL_SLOT": self.host.bead_env["TL_SLOT"], **env}  # the slot's name only: its host paths mean nothing inside
        art = forward.pop("TL_ARTIFACTS", "")
        name = "tl-check-" + "".join(ch if ch.isalnum() or ch in "_.-" else "-" for ch in f"{self.host.run_dir.name}-{c.id}")
        cmd = [sys.executable, str(RUNNER), "--image", self._image, "--name", name, "--art", art]
        cmd += [x for k, v in forward.items() for x in ("--env", f"{k}={v}")]
        return [*cmd, "--", *argv], f"in container {self._image}"

    def _ready(self) -> str:
        if self._why is None:
            self._why = self._probe()
            if self._why:
                self.host.warn(f"container checks run on the host: {self._why[len('on host ('):-1]}")
        return self._why

    def _probe(self) -> str:
        if not docker_ok(self.spawner):
            return NO_DOCKER
        spec = self.host.cfg.container
        image = spec.image if spec and spec.image else self._build(spec.dockerfile) if spec else ""
        self._image = image
        return "" if image else NO_IMAGE

    def _build(self, dockerfile: str) -> str:
        path = Path(self.host.wt) / dockerfile
        try:
            tag = "task-loop-check:" + hashlib.sha1(path.read_bytes()).hexdigest()[:10]  # a new Dockerfile is a new image
        except OSError:
            return ""
        if _docker(self.spawner, "image", "inspect", tag) == 0:
            return tag
        self.host.log.note(f"building the check image {tag}")
        return tag if _docker(self.spawner, "build", "-q", "-f", str(path), "-t", tag, str(path.parent)) == 0 else ""


def _docker(spawner: Spawner, *args: str) -> int:
    try:
        return spawner.run(["docker", *args]).exit
    except OSError:
        return 1


def docker_ok(spawner: Spawner) -> bool:
    try:
        return spawner.run(["docker", "info"], timeout_s=DOCKER_WAIT_S).exit == 0
    except OSError:
        return False
