"""A green gate can certify only the inputs its checks actually observed."""
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit
from support.narrow_hosts import FakeGateHost

from taskloop.app.land.gate import Gate, GatePass, Problem, ProblemKind
from taskloop.contracts.checks import Check, CheckRun
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import engine_digest
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class MovingGit(ScriptedGit):
    def __init__(self) -> None:
        super().__init__()
        self.refs = {"HEAD": "head", "HEAD^{tree}": "tree", "origin/main": "base"}

    def rev_parse(self, d: str, rev: str) -> str:
        return self.refs[rev]


class Worktree:
    tree = TreeSha("tree")

    def tree_hash(self) -> TreeSha:
        return self.tree


class Checking:
    def __init__(self, host: FakeGateHost, move: Callable[[], None]) -> None:
        self.host, self.move = host, move

    def gate_green(self, clean: bool = False) -> bool:
        return False

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = True, show_clean: bool = False,
                  clean: bool = False) -> CheckRun:
        h = self.host
        run = CheckRun(round=1, tree=h.checkout.tree_hash(), base=BaseSha(h.git.rev_parse(h.wt, h.cfg.base)),
                       config=engine_digest(h.cfg))
        self.move()
        return run


class GateIdentity(Case):
    def setup_method(self) -> None:
        self.git = MovingGit()
        cfg = EngineConfig(checks=[CheckSpec(id=CheckId("gate"), argv=["gate"], run="gate")])
        self.host = FakeGateHost(self.git, cfg, RunLog(fake_stores().run_log("run")))
        self.worktree = Worktree()
        self.host.checkout = self.worktree

    def run_gate(self, move: Callable[[], None]) -> GatePass | Problem:
        self.host.checker = Checking(self.host, move)
        return Gate(self.host).run()

    def assert_stale(self, got: GatePass | Problem) -> None:
        assert isinstance(got, Problem)
        assert isinstance(got, Problem)
        assert got.kind == ProblemKind.STALE
        assert self.host.gate_log is None

    def test_tree_changed_during_checks_issues_no_token(self) -> None:
        def move() -> None:
            self.git.refs["HEAD^{tree}"] = "new-tree"
            self.worktree.tree = TreeSha("new-tree")
        self.assert_stale(self.run_gate(move))

    def test_uncommitted_files_changed_during_checks_issue_no_token(self) -> None:
        def move() -> None:
            self.worktree.tree = TreeSha("dirty-tree")
        self.assert_stale(self.run_gate(move))

    def test_base_moved_during_checks_issues_no_token(self) -> None:
        self.assert_stale(self.run_gate(lambda: self.git.refs.update({"origin/main": "new-base"})))

    def test_head_moved_to_same_tree_during_checks_issues_no_token(self) -> None:
        self.assert_stale(self.run_gate(lambda: self.git.refs.update({"HEAD": "new-head"})))

    def test_config_changed_during_checks_issues_no_token(self) -> None:
        def move() -> None:
            self.host.cfg = self.host.cfg.replace(gate_timeout_min=5)
        self.assert_stale(self.run_gate(move))

    def test_unchanged_inputs_issue_the_captured_token(self) -> None:
        got = self.run_gate(lambda: None)
        assert isinstance(got, GatePass)
        assert isinstance(got, GatePass)
        assert (got.tree, got.base, got.config) == ("tree", "base", engine_digest(self.host.cfg))
