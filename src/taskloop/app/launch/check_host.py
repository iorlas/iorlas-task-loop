"""CliHost: standalone checks through the engine's runner, cache and persistent run evidence."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from taskloop.adapters import check_files, treehash
from taskloop.adapters.threadflag import ThreadFlag
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.land.checkout import Checkout
from taskloop.app.run.shell import Shell
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import WaitWhat
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.locator import RunBundle
from taskloop.contracts.ports import Git, Spawner
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class _Waits:
    def note_slot_waits(self, text: str, wall: float) -> None: ...
    def start(self, what: WaitWhat, holder: str = "", until: float | None = None) -> str:
        return ""

    def add(self, secs: float, what: WaitWhat, wid: str | None = None) -> None: ...


class _NewFiles:
    """A person's check run stages nothing: no new file is one a stage meant."""

    def new_file_kind(self, path: str) -> str:
        return "unexplained"


class CliHost:
    killed = ThreadFlag()
    wall_hit = ThreadFlag()

    def __init__(
        self,
        wt: str | Path,
        cfg: EngineConfig,
        stores: Stores,
        *,
        bundle: RunBundle,
        log: RunLog,
        env: Env,
        spawner: Spawner,
        git: Git,
    ) -> None:
        self.env = env
        self.spawner = spawner
        self.git = git
        self.wt = str(wt)
        self.cfg = cfg
        self.stores = stores
        self.bead = "tl-check-" + check_files.repo_key(git, str(wt))
        self.run_id = bundle.run
        self.log = log
        self.checklog = CheckLog(self.log)
        self.run_dir = bundle.dir
        self.bead_env: Mapping[str, str] = {EnvVar.TL_SLOT.value: "check"}
        self.killed = self.wall_hit = False
        self.halt = threading.Event()
        self.tree_memo: tuple[treehash.State, TreeSha] | None = None
        self.newfiles = _NewFiles()
        self.steps: Any = None  # the step book is the engine's; a person's run has none
        self.shell, self.checkout, self.waits = Shell(self), Checkout(self), _Waits()
        self.tree_writer = self.checkout

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None,
           stop: threading.Event | None = None) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop)

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(why)

    def warn(self, text: str) -> None:
        print(f"warning: {text}")

    def detail(self, lines: list[str]) -> None: ...

    def halt_point(self, when: bool = True, wait: float = 0) -> None: ...
