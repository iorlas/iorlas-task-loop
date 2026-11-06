"""A receipt `tl check` wrote in a clean worktree counts for `tl land-stack` when it judges from that worktree (detached at the oid
too), and a refusal names, per step, the first key field that differs from the newest receipt on that tree and base."""
import json
import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

from taskloop.adapters import check_files, childenv
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.execution import check_env
from taskloop.app.checks.keydiff import first_difference
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.stackgate import StackGate
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.config import load
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import TreeEntry
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git, Ran
from taskloop.contracts.runkey import BaseSha, Digest
from taskloop.contracts.slots import Checkout
from taskloop.domain.checks.specs import repo_check
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog

OID, TREE, BASE = "1550b77c" + "0" * 32, TreeSha("tree-1"), BaseSha("base-1")
INPUTS = ["src/**"]
PROFILE = {"engine": {"resources": {"unity": {"limit": 1}}, "checks": [
    {"id": "fmt", "argv": ["true"], "group": "static", "run": "gate"},
    {"id": "unity-check", "argv": ["true"], "group": "static", "run": "gate", "needs": ["unity"]},
    {"id": "unity-tests", "argv": ["true"], "group": "tests", "run": "both", "needs": ["unity"], "inputs": INPUTS,
     "when": INPUTS}]}}


class Checkouts:
    """Two checkouts of one repo: the main one (on main, other build output) and a clean detached worktree at OID."""

    def __init__(self, root: Path) -> None:
        self.main, self.wt = root / "main", root / "wt"
        for d, text in ((self.main, "main build"), (self.wt, "worktree build")):
            (d / "src/obj").mkdir(parents=True)
            (d / "src/obj/project.assets.json").write_text(text)
        self.git = mock.create_autospec(Git, instance=True)
        self.git.config_get.return_value = "git@example.com:o/lifesim.git"
        self.git.ls_tree.side_effect = self.ls_tree
        self.git.show.return_value = json.dumps(PROFILE)
        self.git.ls_files.return_value = ["src/obj/project.assets.json"]  # gitignored, under the check's inputs
        self.git.checkouts.return_value = [Checkout(path=str(self.main), branch="main", main=True),
                                           Checkout(path=str(self.wt), branch="", main=False)]
        self.git.rev_parse.side_effect = lambda d, rev: {"HEAD": OID if d == str(self.wt) else "main-oid",
                                                         "HEAD^{tree}": TREE, f"{OID}^{{tree}}": TREE, "origin/main": BASE}[rev]
        self.git.dirty.return_value = False

    @staticmethod
    def ls_tree(d, rev, *paths, recursive=False):
        if paths:
            return [TreeEntry(mode="100644", kind="blob", oid="profile", path=".task-loop.json")]
        return [TreeEntry(mode="100644", kind="blob", oid="s1", path="src/Sim.cs"),
                TreeEntry(mode="100644", kind="blob", oid="p1", path=".task-loop.json")]


def write_receipts(stores, git: Git, wt: str) -> RunMemo:
    """What `tl check --repo wt` leaves: a pass of every gate step under the key the runner's memo gives it."""
    engine = load(PROFILE).engine
    env = {**childenv.reaching(childenv.current_env(Env())), **check_env()}
    memo = RunMemo(stores, check_files.repo_key(git, wt), InputKeys(git, wt, TREE), BASE, env, "check-run")
    memo.checks = {c.id: repo_check(c, engine) for c in engine.checks}
    for c in memo.checks.values():
        key = memo.key(c)
        assert key is not None, c.id
        memo.remember(key, CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=0, status="passed"), 1, "")
    return memo


class StackGateKeys(Case):
    def setup_method(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Checkouts(Path(tmp.name))
        self.stores = fake_stores()
        self.spawner = spawner = mock.Mock()
        log = RunLog(self.stores.run_log("land"), run_id="land", host="h")
        self.gate = StackGate(Cmds(spawner, log, str(self.repo.main)), self.repo.git, self.stores, str(self.repo.main),
                              "origin/main", ["tl"])
        self.engine = load(PROFILE).engine

    def test_a_clean_detached_worktree_at_the_oid_is_where_the_gate_judges(self):
        write_receipts(self.stores, self.repo.git, str(self.repo.wt))
        assert self.gate.worktree("task/lifesim-fmtfix-r3", OID) == str(self.repo.wt)
        self.gate.require("task/lifesim-fmtfix-r3", OID)  # green: no Stop, no `tl check` run
        self.spawner.run.assert_not_called()

    def test_the_main_checkout_cannot_reproduce_a_worktree_receipt_over_ignored_inputs(self):
        """The production failure: judged from the main checkout, the gitignored build output under `inputs` is another file."""
        write_receipts(self.stores, self.repo.git, str(self.repo.wt))
        assert self.gate.red(self.engine, TREE, BASE, str(self.repo.wt)) == []
        assert self.gate.red(self.engine, TREE, BASE, str(self.repo.main)) == [CheckId("unity-tests")]
        assert re.search(r"^inputs differ \(expected [0-9a-f]{12} found [0-9a-f]{12}\)", self.gate.why[CheckId("unity-tests")])

    def test_a_refusal_names_the_first_differing_field_of_each_step(self):
        write_receipts(self.stores, self.repo.git, str(self.repo.wt))
        self.repo.git.checkouts.return_value = self.repo.git.checkouts.return_value[:1]  # no worktree has it out
        self.spawner.run.return_value = Ran(exit=0)  # the gate's own run in a fresh worktree writes nothing here
        with pytest.raises(Stop) as stop:
            self.gate.require("task/lifesim-fmtfix-r3", OID)
        assert "is still not green for " in stop.value.why
        assert self.repo.git.add_worktree.called

    def test_a_step_with_no_receipt_on_this_tree_says_so(self):
        assert self.gate.red(self.engine, TREE, BASE, str(self.repo.wt)) == ["fmt", "unity-check", "unity-tests"]
        assert set(self.gate.why.values()) == {f"no green run of tree {TREE[:12]} under `true`"}

    def test_a_changed_command_still_misses_and_is_named(self):
        write_receipts(self.stores, self.repo.git, str(self.repo.wt))
        changed = load({"engine": {**PROFILE["engine"], "checks": [{**PROFILE["engine"]["checks"][0], "argv": ["false"]}]}}).engine
        assert self.gate.red(changed, TREE, BASE, str(self.repo.wt)) == ["fmt"]
        assert self.gate.why[CheckId("fmt")].startswith("cmd differs (expected ")


class FirstDifference(Case):
    def test_fields_are_compared_in_key_order_and_equal_keys_have_none(self):
        memo = write_receipts(fake_stores(), _flat_git(), "/unused")
        key = memo.receipts[CheckId("fmt")].key
        assert first_difference(key, key) == ""
        assert (
            first_difference(key, key.replace(env=Digest("e" * 40), execution=Digest("x")))
            == f"env differs (expected {key.env[:12]} found eeeeeeeeeeee)"
        )
        assert first_difference(key, key.replace(dependencies=Digest("d" * 64))) == "dependencies differ (expected none found dddddddddddd)"


def _flat_git() -> Git:
    git = mock.create_autospec(Git, instance=True)
    git.config_get.return_value = "repo"
    git.ls_tree.side_effect = Checkouts.ls_tree
    git.ls_files.return_value = []
    return git
