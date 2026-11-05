"""A pass of a check with `closure_cmd` is carried over a base move when the files its result depends on are the same in the branch and in
the branch merged into the moved base; a changed file, a new test of main that imports the changed module, a conflict, or a failing
closure command each make it run again."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from support.case import Case

from taskloop.adapters import check_files, childenv
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.execution import check_env
from taskloop.app.land.carry import MERGE, Carry
from taskloop.app.land.cmds import Cmds
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.config import load
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import TreeEntry
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git, Ran
from taskloop.domain.checks.specs import repo_check
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog

OID, TREE, B1, B2 = "1550b77c" + "0" * 32, TreeSha("tree-1"), "base-1", "base-2"
PROFILE = {"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate", "closure_cmd": ["affected", "--closure"]}]}}
BRANCH = {"src/a.py": "A = 1\n", "tests/test_a.py": "import a\n"}


class Spawns:
    """`git merge` writes what main added into the throwaway worktree; the closure command lists the files of its scenario that exist."""

    def __init__(self, tdir: Path, main: dict[str, str], listed: list[str], merge_exit: int = 0, closure_exit: int = 0) -> None:
        self.tdir, self.main, self.listed, self.merge_exit, self.closure_exit = tdir, main, listed, merge_exit, closure_exit
        self.calls: list[list[str]] = []

    def run(self, argv, cwd=None, **_kw):
        self.calls.append(list(argv))
        if argv[: len(MERGE)] == MERGE:
            for path, text in {**BRANCH, **self.main}.items():
                (Path(cwd) / path).parent.mkdir(parents=True, exist_ok=True)
                (Path(cwd) / path).write_text(text)
            return Ran(exit=self.merge_exit)
        if argv[0] == "affected":
            return Ran(exit=self.closure_exit, out="\n".join(p for p in self.listed if (Path(cwd) / p).is_file()))
        return Ran(exit=0)


class CarryCase(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tdir = Path(tmp.name) / "wt"
        for path, text in BRANCH.items():
            (self.tdir / path).parent.mkdir(parents=True, exist_ok=True)
            (self.tdir / path).write_text(text)
        self.git = git = mock.create_autospec(Git, instance=True)
        git.config_get.return_value = "git@example.com:o/r.git"
        git.show.return_value = json.dumps(PROFILE)
        git.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="s1", path="src/a.py")]
        git.ls_files.return_value = []
        git.merge_base.return_value = "merge-base"
        git.rev_parse.side_effect = lambda d, rev: {"HEAD": OID, "HEAD^{tree}": TREE}.get(rev, "x")
        self.stores = fake_stores()
        self.engine = load(PROFILE).engine
        self.memo = self.memo_at(B1)
        check = repo_check(self.engine.checks[0], self.engine)
        self.memo.checks = {check.id: check}
        key = self.memo.key(check)
        assert key is not None
        self.memo.run_id = "check-run"
        self.memo.remember(key, CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=0, status="passed"), 1, "")

    def memo_at(self, base: str) -> RunMemo:
        env = {**childenv.reaching(childenv.current_env(Env())), **check_env()}
        return RunMemo(self.stores, check_files.repo_key(self.git, str(self.tdir)), InputKeys(self.git, str(self.tdir), TREE), base, env)

    def carry(self, main: dict[str, str], listed: list[str], **kw) -> tuple[bool, Spawns]:
        spawns = Spawns(self.tdir, main, listed, **kw)
        log = RunLog(self.stores.run_log("land"), run_id="land", host="h")
        carried = Carry(Cmds(spawns, log, str(self.tdir)), self.git, self.stores, str(self.tdir), Env()).carried(
            self.engine, "suite", OID, TREE, B2, str(self.tdir))
        return carried, spawns

    def hits(self) -> bool:
        memo = self.memo_at(B2)
        memo.checks = {c.id: repo_check(c, self.engine) for c in self.engine.checks}
        return memo.result(memo.checks["suite"]) is not None

    def test_an_unchanged_closure_carries_the_pass_to_the_moved_base(self):
        assert not self.hits()
        carried, _ = self.carry(main={"docs/x.md": "news\n"}, listed=["src/a.py", "tests/test_a.py"])
        assert carried and self.hits()
        got = self.memo_at(B2)
        got.checks = {c.id: repo_check(c, self.engine) for c in self.engine.checks}
        assert got.hit(got.key(got.checks["suite"])).origin == "check-run"

    def test_a_file_of_the_closure_that_main_changed_is_a_miss(self):
        carried, _ = self.carry(main={"src/a.py": "A = 2\n"}, listed=["src/a.py", "tests/test_a.py"])
        assert not carried and not self.hits()

    def test_a_new_test_of_main_that_imports_the_changed_module_is_a_miss(self):
        carried, _ = self.carry(main={"tests/test_new.py": "import a\n"}, listed=["src/a.py", "tests/test_a.py", "tests/test_new.py"])
        assert not carried and not self.hits()

    def test_a_merge_conflict_is_a_miss(self):
        carried, spawns = self.carry(main={}, listed=["src/a.py"], merge_exit=1)
        assert not carried and not self.hits()
        assert ["git", "merge", "--abort"] in spawns.calls

    def test_a_failing_closure_command_is_a_miss(self):
        carried, _ = self.carry(main={}, listed=["src/a.py"], closure_exit=2)
        assert not carried and not self.hits()

    def test_a_check_without_closure_cmd_never_carries(self):
        self.engine = load({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}).engine
        carried, spawns = self.carry(main={}, listed=["src/a.py"])
        assert not carried and spawns.calls == []

    def test_the_throwaway_merge_worktree_is_removed(self):
        self.carry(main={}, listed=["src/a.py"])
        assert self.git.remove_worktree_force.called
