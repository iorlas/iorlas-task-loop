"""Carry mode `queue_parent`: a pass made at the queue parent Q(N-1) counts under base = main when main has the parent's tree and the rest
of the key is the same; the closure mode is not used."""
import json
from unittest import mock

import pytest
from support.memstores import fake_stores

from taskloop.adapters import check_files, childenv
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.execution import check_env
from taskloop.app.land.carry import Carry
from taskloop.app.land.cmds import Cmds
from taskloop.domain.checks.specs import repo_check
from taskloop.stores.runlog import RunLog
from tlkernel.checks import CheckResult
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha
from tltestkit.tmpdir import TemporaryDirectory

TREE, PARENT, MAIN = TreeSha("tree-n"), "q-parent", "main-sha"
SUITE = CheckId("suite")
PROFILE = {"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}  # no closure_cmd: the closure mode never carries it


class World:
    def __init__(self, tmp: str, trees: dict[str, str]) -> None:
        self.git = git = mock.create_autospec(Git, instance=True)
        git.config_get.return_value = "git@example.com:o/r.git"
        git.show.return_value = json.dumps(PROFILE)
        git.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="s1", path="src/a.py")]
        git.ls_files.return_value = []
        git.rev_parse.side_effect = lambda d, rev: trees.get(rev, "x")
        self.tmp, self.stores, self.engine = tmp, fake_stores(), load(PROFILE).engine

    def memo_at(self, base: str, tree: TreeSha = TREE) -> RunMemo:
        env = {**childenv.reaching(childenv.current_env(Env())), **check_env()}
        memo = RunMemo(self.stores, check_files.repo_key(self.git, self.tmp), InputKeys(self.git, self.tmp, tree), BaseSha(base), env)
        memo.checks = {c.id: repo_check(c, self.engine) for c in self.engine.checks}
        return memo

    def pass_at(self, base: str, tree: TreeSha = TREE) -> None:
        memo = self.memo_at(base, tree)
        check = memo.checks[SUITE]
        key = memo.key(check)
        assert key is not None
        memo.run_id = "queue-run"
        memo.remember(key, CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=0, status="passed"), 1, "")

    def carry(self, tree: TreeSha = TREE) -> bool:
        log = RunLog(self.stores.run_log("land"), run_id="land", host="h")
        carry = Carry(Cmds(mock.Mock(), log, self.tmp), self.git, self.stores, self.tmp, Env())
        return carry.queue_carried(self.engine, "suite", tree, MAIN, PARENT, self.tmp)

    def hits(self, base: str = MAIN) -> bool:
        memo = self.memo_at(base)
        return memo.result(memo.checks[SUITE]) is not None


@pytest.fixture
def world():
    with TemporaryDirectory() as tmp:
        yield World(tmp, {f"{MAIN}^{{tree}}": "T1", f"{PARENT}^{{tree}}": "T1"})


def test_a_pass_at_the_queue_parent_counts_under_main_when_the_trees_match(world):
    world.pass_at(PARENT)
    assert not world.hits()
    assert world.carry() and world.hits()
    hit = world.memo_at(MAIN)
    assert hit.hit(hit.key(hit.checks[SUITE])).origin == "queue-run"  # origin names the run that made it


def test_a_main_with_another_tree_than_the_parent_is_a_miss(world):
    world.pass_at(PARENT)
    world.git.rev_parse.side_effect = lambda d, rev: {f"{MAIN}^{{tree}}": "T2", f"{PARENT}^{{tree}}": "T1"}.get(rev, "x")
    assert not world.carry() and not world.hits()


def test_a_pass_of_another_tree_is_a_miss(world):
    world.pass_at(PARENT, TreeSha("tree-other"))
    assert not world.carry() and not world.hits()


def test_a_pass_at_another_base_is_a_miss(world):
    world.pass_at("some-other-base")
    assert not world.carry() and not world.hits()


def test_a_key_field_that_differs_is_a_miss(world):
    world.pass_at(PARENT)
    world.engine = load({"engine": {"checks": [{"id": "suite", "argv": ["false"], "run": "gate"}]}}).engine
    assert not world.carry() and not world.hits()


def test_an_unknown_step_is_a_miss(world):
    world.pass_at(PARENT)
    assert not Carry(Cmds(mock.Mock(), RunLog(world.stores.run_log("land"), run_id="l", host="h"), world.tmp), world.git, world.stores,
                     world.tmp, Env()).queue_carried(world.engine, "nope", TREE, MAIN, PARENT, world.tmp)
