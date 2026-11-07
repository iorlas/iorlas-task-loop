"""CliHost: standalone checks through the engine's runner, cache and persistent run evidence."""
import threading
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from tlgate.checklog import CheckLog
from tlgate.execution import check_env
from tlgate.host import CheckoutView
from tlkernel import check_files, treehash
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ids import TreeSha
from tlkernel.locator import RunBundle
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner
from tlkernel.waitenums import WaitWhat

from taskloop.adapters import ident
from taskloop.adapters.ignored import ignored_by
from taskloop.adapters.threadflag import ThreadFlag
from taskloop.app.checks.shell import Shell
from taskloop.app.land.checkout import Checkout
from taskloop.app.launch.staged import StagedCheckout
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


class _Waits:
    def note_slot_waits(self, text: str, wall: float) -> None: ...
    def start(self, what: WaitWhat, holder: str = "", until: float | None = None, lane: str = "", check: str = "") -> str:
        return ""

    def add(self, secs: float, what: WaitWhat, wid: str | None = None, lane: str = "", check: str = "") -> None: ...


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
        staged: list[str] | None = None,  # tl check --staged: the paths the commit changes, what `when` and pass_files see as changed
    ) -> None:
        self.env = env
        self.home = ConfigDir(ident.config_dir(env))  # gateplan notes its once-per-run warnings under it
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
        self.bead_env: Mapping[str, str] = check_env()
        self.killed = self.wall_hit = False
        self.halt = threading.Event()
        self.tree_memo: tuple[treehash.State, TreeSha] | None = None
        self.accepted_new: list[str] = []  # a person's check run stages nothing: no new file is one a stage meant
        self.plan_data: Mapping[str, object] | None = None
        self.steps: Any = None  # the step book is the engine's; a person's run has none
        self.shell, self.waits = Shell(self), _Waits()
        whole = Checkout(self, ignore_rules=partial(ignored_by, git, str(wt)))
        self.tree_writer = whole
        self.checkout: CheckoutView = StagedCheckout(whole, staged) if staged is not None else whole

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None,
           stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd, stop, network=network)

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(why)

    def warn(self, text: str) -> None:
        print(f"warning: {text}")

    def detail(self, lines: list[str]) -> None: ...

    def halt_point(self, when: bool = True, wait: float = 0) -> None: ...
