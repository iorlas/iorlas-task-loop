"""Release hosts and shells over independent in-memory test-kit stores."""
import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

from tlgate.api import authorization
from tlgate.testing import FakeGateStores
from tlkernel.beadsport import Beads
from tlkernel.checks import CheckResult
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.identity import Identity
from tlkernel.ids import CheckId, TreeSha
from tlkernel.lockenums import LockWhat
from tlkernel.paths import ConfigDir, default_root
from tlkernel.runkey import BaseSha, Digest, RunKey
from tltestkit.membeads import MemBeads
from tltestkit.memdoc import MemLockTable

from tlrelease.gate import GateHost
from tlrelease.shell import Done, Shell


class FakeReleaseHost:
    """The release's machine capabilities, with no shell adapter or real process."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = MemBeads()
        self.locks = MemLockTable(alive=lambda pid: True)
        self.stores = FakeGateStores()
        self.host = GateHost(
            config_dir=self.config_dir, claude_dir=self.claude_dir, identity=self.identity, plugin_root=root,
            land_lock_path=lambda cfg, url: cfg.lock_file("land-" + hashlib.sha1(url.encode()).hexdigest()[:12] + ".lock"),
            os_lock=self.os_lock, bd_store=self.bd_store,
            repo_root=lambda repo: str(Path(repo).resolve()),
            memo_for=lambda git, wt, cfg, tree, base, env: authorization.memo_for(self.stores, git, wt, cfg, tree, base, env),
        )

    def bd_store(self, actor: str, repo: Path) -> Beads:
        self.store.actor = actor
        return self.store

    @contextmanager
    def os_lock(self, path: Path, holder: str, waiting: Callable[[str], None]) -> Iterator[Path]:
        with self.locks.hold(LockWhat.LAND, str(path), holder, waiting=lambda rec: waiting(rec.holder if rec else "?")):
            yield path

    def config_dir(self, env: Env) -> Path:
        directory = default_root(env)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def claude_dir(self, env: Env) -> Path:
        return Path(env.get("CLAUDE_CONFIG_DIR") or self.root / "claude")

    def identity(self, env: Env) -> Identity:
        return Identity(actor=env.get("TASK_LOOP_ACTOR") or "fake", home=str(default_root(env)),
                        session=env.get("TASK_LOOP_SESSION"))


def quiet_shell(calls: list[list[str]] | None = None) -> Shell:
    """A recording, successful shell whose git and spawner cannot start processes."""
    log = calls if calls is not None else []

    def run(cmd: list[str], cwd: str | Path | None, check: bool = True, **_: object) -> Done:
        log.append(cmd)
        return Done(0, "", "")

    return Shell(fetch=lambda cwd: None, run=run, say=lambda msg: None, port=Mock(), spawner=Mock())


HOST_CASES = ("paths", "identity", "lock", "repo", "beads", "memo")


def check_host(host: GateHost, env: Env, repo: Path, case: str) -> None:
    """One capability contract, shared by the fake and the shell binding."""
    if case == "paths":
        cfg = host.config_dir(env)
        assert cfg == Path(env.get("XDG_CONFIG_HOME")) / "task-loop"
        assert cfg.is_dir()
        assert host.claude_dir(env) == Path(env.get("CLAUDE_CONFIG_DIR"))
        assert isinstance(host.plugin_root, Path)
    elif case == "identity":
        who = host.identity(env)
        assert who.actor == env.get("TASK_LOOP_ACTOR")
        assert who.session == env.get("TASK_LOOP_SESSION")
        assert who.config.root == host.config_dir(env)
    elif case == "lock":
        path = host.land_lock_path(ConfigDir(host.config_dir(env)), str(repo))
        assert path == host.land_lock_path(ConfigDir(host.config_dir(env)), str(repo))
        with host.os_lock(path, "release contract", lambda who: None):
            pass
        with host.os_lock(path, "release contract again", lambda who: None):
            pass
    elif case == "repo":
        assert host.repo_root(str(repo)) == str(repo)
    elif case == "beads":
        assert vars(host.bd_store(env.get("TASK_LOOP_ACTOR"), repo))["actor"] == env.get("TASK_LOOP_ACTOR")
    elif case == "memo":
        git = Mock()
        git.common_dir.return_value = str(repo / ".git")
        tree, base = TreeSha("tree"), BaseSha("base")
        memo = host.memo_for(git, str(repo), EngineConfig(), tree, base, env)
        key = RunKey(check=CheckId("suite"), cmd=Digest("cmd"), config=Digest("cfg"), toolchain=Digest("tools"),
                     tree=tree, base=base, inputs=Digest("inputs"), selected=Digest(""), env=Digest("env"))
        assert memo.hit(key) is None
        result = CheckResult(id=key.check, cmd="just test", group="tests", exit=0, status="passed")
        memo.remember(key, result, 0, "")
        again = host.memo_for(git, str(repo), EngineConfig(), tree, base, env)
        found = again.hit(key)
        assert found is not None and found.result == result
        assert again.hit(key.replace(tree=TreeSha("different"))) is None
    else:
        raise AssertionError(case)
