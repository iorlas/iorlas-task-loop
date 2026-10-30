"""CliHost: the CheckHost of `tl check`, a person's run of the registry in any worktree. The same Checker runs the same steps through the
same cache; the host has no bead, no step book and no budget: its log is in memory, its step logs are in a folder that is removed after,
and the only files it writes under the config folder are the check cache and the duration history the engine's checks already use."""
import shutil
import tempfile
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from taskloop.adapters import check_files, gitrepo, treehash
from taskloop.adapters.gitenv import git_env
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.land.checkout import Checkout
from taskloop.app.run.shell import Shell
from taskloop.app.wire import real
from taskloop.contracts import paths
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Spawner
from taskloop.stores.bundle import Stores
from taskloop.stores.memory import fake_stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


class _Waits:
    def note_slot_waits(self, text: str, wall: float) -> None: ...
    def start(self, what: str) -> str:
        return ""

    def add(self, secs: float, what: str, wid: str | None = None) -> None: ...


class _NewFiles:
    """A person's check run stages nothing: no new file is one a stage meant."""

    def new_file_kind(self, path: str) -> str:
        return "unexplained"


class CliHost:
    def __init__(self, wt: str | Path, cfg: EngineConfig, stores: Stores | None = None, root: Path | None = None,
                 spawner: Spawner | None = None, *, env: Env) -> None:
        self.env = env
        self.spawner = spawner or real.spawner(env)
        self.wt: str | Path = Path(wt)
        self.cfg = cfg
        self.stores = stores or real_stores(paths.ConfigDir(root))
        self.bead = "tl-check-" + check_files.repo_key(str(wt), git_env(wt))
        self.log = RunLog(fake_stores().run_log("check"))
        self.checklog = CheckLog(self.log)
        self.run_dir = Path(tempfile.mkdtemp(prefix="tl-check-"))
        self.bead_env: Mapping[str, str] = {EnvVar.TL_SLOT.value: "check"}
        self.killed = self.wall_hit = False
        self.halt = threading.Event()
        self.tree_memo: tuple[treehash.State, TreeSha] | None = None
        self.newfiles = _NewFiles()
        self.steps: Any = None  # the step book is the engine's; a person's run has none
        self.shell, self.checkout, self.waits = Shell(self), Checkout(self), _Waits()
        self.tree_writer = self.checkout

    def sh(self, cmd: Sequence[str], timeout: float = 3600, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "command", cwd: Path | None = None) -> tuple[int, str]:
        return self.shell.run(cmd, timeout, check, save, env, pin, what, cwd)

    def git(self, *args: str) -> str:
        return gitrepo.git(*args, cwd=self.wt)

    def blocked_for(self, why: str, kind: str) -> Exception:
        return RuntimeError(why)

    def warn(self, text: str) -> None:
        print(f"warning: {text}")

    def detail(self, lines: list[str]) -> None: ...

    def halt_point(self, when: bool = True, wait: float = 0) -> None: ...

    def close(self) -> None:
        shutil.rmtree(self.run_dir, ignore_errors=True)
