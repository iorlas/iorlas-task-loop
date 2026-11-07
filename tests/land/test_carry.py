"""A pass of a check with `closure_cmd` is carried over a base move when the files its result depends on are the same in the branch and in
the branch merged into the moved base; a changed file, a new test of main that imports the changed module, a conflict, or a failing
closure command each make it run again."""
import json
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from support.memstores import fake_stores

from taskloop.app.land.carry import MERGE, Carry
from taskloop.app.land.cmds import Cmds
from taskloop.stores.runlog import RunLog
from tlgate.cache import InputKeys, RunMemo
from tlgate.domain.specs import repo_check
from tlgate.execution import check_env
from tlkernel import check_files, childenv
from tlkernel.checks import CheckResult
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.procport import Ran
from tlkernel.runkey import BaseSha
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

OID, TREE, B1, B2 = "1550b77c" + "0" * 32, TreeSha("tree-1"), "base-1", "base-2"
SUITE = CheckId("suite")
PROFILE = {"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate", "closure_cmd": ["affected", "--closure"]}]}}
BRANCH = {"src/a.py": "A = 1\n", "tests/test_a.py": "import a\n"}


class Spawns:
    """`git merge` writes what main added into the throwaway worktree; the closure command lists the files of its scenario that exist."""

    def __init__(self, tdir: Path, main: dict[str, str], listed: list[str], merge_exit: int = 0, closure_exit: int = 0) -> None:
        self.tdir, self.main, self.listed, self.merge_exit, self.closure_exit = tdir, main, listed, merge_exit, closure_exit
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
            extra: Mapping[str, str] | None = None, timeout_s: float | None = None, capture: bool = True) -> Ran:
        assert cwd is not None
        self.calls.append(list(argv))
        if tuple(argv[: len(MERGE)]) == MERGE:
            for path, text in {**BRANCH, **self.main}.items():
                (Path(cwd) / path).parent.mkdir(parents=True, exist_ok=True)
                (Path(cwd) / path).write_text(text)
            return Ran(exit=self.merge_exit)
        if argv[0] == "affected":
            return Ran(exit=self.closure_exit, out="\n".join(p for p in self.listed if (Path(cwd) / p).is_file()))
        return Ran(exit=0)


class CarryCase(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
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
        keys = InputKeys(self.git, str(self.tdir), TREE)
        return RunMemo(self.stores, check_files.repo_key(self.git, str(self.tdir)), keys, BaseSha(base), env)

    def carry(self, main: dict[str, str], listed: list[str], tree: TreeSha = TREE, **kw) -> tuple[bool, Spawns]:
        spawns = Spawns(self.tdir, main, listed, **kw)
        self.log = RunLog(self.stores.run_log("land"), run_id="land", host="h")
        self.notes: list[str] = []
        self.enterContext(mock.patch.object(self.log, "note", self.notes.append))
        carried = Carry(Cmds(spawns, self.log, str(self.tdir)), self.git, self.stores, str(self.tdir), Env()).carried(
            self.engine, "suite", OID, tree, B2, str(self.tdir))
        return carried, spawns

    def said(self) -> str:
        return "\n".join(self.notes)

    def hits(self) -> bool:
        memo = self.memo_at(B2)
        memo.checks = {c.id: repo_check(c, self.engine) for c in self.engine.checks}
        return memo.result(memo.checks[SUITE]) is not None

    def test_an_unchanged_closure_carries_the_pass_to_the_moved_base(self):
        assert not self.hits()
        carried, _ = self.carry(main={"docs/x.md": "news\n"}, listed=["src/a.py", "tests/test_a.py"])
        assert carried and self.hits()
        got = self.memo_at(B2)
        got.checks = {c.id: repo_check(c, self.engine) for c in self.engine.checks}
        hit = got.hit(got.key(got.checks[SUITE]))
        assert hit is not None and hit.origin == "check-run"

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

    def test_a_carry_says_it_carried(self):
        self.carry(main={"docs/x.md": "news\n"}, listed=["src/a.py", "tests/test_a.py"])
        assert "carry: suite carried" in self.said()

    def test_a_miss_names_the_files_of_the_closure_that_differ(self):
        self.carry(main={"src/a.py": "A = 2\n"}, listed=["src/a.py", "tests/test_a.py"])
        assert "carry: suite not carried, the closure differs: src/a.py" in self.said()

    def test_a_tree_with_no_earlier_pass_says_so(self):
        self.carry(main={}, listed=["src/a.py"], tree=TreeSha("tree-other"))
        assert "carry: suite not carried, no earlier pass of this tree" in self.said()

    def test_a_conflict_says_so(self):
        self.carry(main={}, listed=["src/a.py"], merge_exit=1)
        assert "carry: suite not carried, the branch does not merge into the base" in self.said()
