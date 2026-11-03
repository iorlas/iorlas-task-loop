"""Box prepares argv only after the required environment has been admitted."""
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from taskloop.adapters import childenv
from taskloop.app.checks.execution import HOST, EnvironmentUnavailable, ReadyExecution, resolve_container
from taskloop.app.checks.host import CheckHost
from taskloop.contracts.checks import Check
from taskloop.contracts.envvars import TL_PREFIX, EnvVar
from taskloop.contracts.ports import Spawner

RUNNER = Path(__file__).parents[2] / "adapters" / "container_run.py"


class Box:
    def __init__(self, host: CheckHost, spawner: Spawner) -> None:
        self.host, self.spawner = host, spawner
        self._execution: ReadyExecution | EnvironmentUnavailable | None = None
        self._lock = threading.Lock()

    def resolve(self, c: Check) -> ReadyExecution | EnvironmentUnavailable:
        if not c.container:
            return HOST
        with self._lock:
            if self._execution is None:
                self._execution = resolve_container(self.host.cfg.container, str(self.host.wt), self.spawner)
            return self._execution

    def plan(self, c: Check, argv: Sequence[str], env: Mapping[str, str]) -> tuple[list[str], str]:
        """(the argv to run, where it runs): the argv itself on the host, the runner's in a container."""
        if not c.container:
            return list(argv), ""
        execution = self.resolve(c)
        if isinstance(execution, EnvironmentUnavailable):
            raise ValueError("environment unavailable: " + execution.reason)
        tl = {k: v for k, v in childenv.current_env(self.host.env).items() if k.startswith(TL_PREFIX)}
        # the slot's name only: its host paths mean nothing inside
        forward = {**tl, EnvVar.TL_SLOT.value: self.host.bead_env[EnvVar.TL_SLOT], **env}
        art = forward.pop(EnvVar.TL_ARTIFACT_DIR, "")
        for host_path in (EnvVar.TL_RUN_DIR, EnvVar.TL_WORKTREE):  # host paths: they mean nothing inside
            forward.pop(host_path, None)
        # The runner sets scratch HOME inside the container. Do not use the host builder here: its hooks and toolchain
        # cache defaults are host paths. Keep the existing explicit forwarding, with credentials and owner config removed.
        forward = {k: v for k, v in forward.items()
                   if k not in childenv.CHECK_SECRETS | childenv.CHECK_HOME_NAMES and not k.startswith("GIT_CREDENTIAL")}
        name = "tl-check-" + "".join(ch if ch.isalnum() or ch in "_.-" else "-" for ch in f"{self.host.run_dir.name}-{c.id}")
        cmd = [sys.executable, str(RUNNER), "--image", execution.image, "--name", name, "--art", art]
        cmd += [x for k, v in forward.items() for x in ("--env", f"{k}={v}")]
        return [*cmd, "--", *argv], f"in container {execution.image}"
