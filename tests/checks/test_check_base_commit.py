"""`tl check --base-commit SHA`: the run is keyed at that commit; without it the base branch is the base and nothing changes."""
import json
from unittest import mock

import support.paths  # noqa: F401
from support.memstores import fake_stores

# isort: split
from taskloop.adapters import check_files
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.execution import check_env
from taskloop.app.launch.check import with_base
from taskloop.domain.checks.specs import repo_check
from tlkernel import childenv
from tlkernel.checks import CheckResult
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha

PROFILE = {"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}
TREE = TreeSha("tree-n")


def world():
    git = mock.create_autospec(Git, instance=True)
    git.config_get.return_value = "git@example.com:o/r.git"
    git.show.return_value = json.dumps(PROFILE)
    git.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="s1", path="src/a.py")]
    git.ls_files.return_value = []
    return git, fake_stores(), load(PROFILE).engine


def memo_at(git, stores, engine, base: str) -> RunMemo:
    env = {**childenv.reaching(childenv.current_env(Env())), **check_env()}
    memo = RunMemo(stores, check_files.repo_key(git, "/wt"), InputKeys(git, "/wt", TREE), BaseSha(base), env)
    memo.checks = {c.id: repo_check(c, engine) for c in engine.checks}
    return memo


def test_a_commit_replaces_the_base_and_none_leaves_the_config_as_it_is():
    cfg = load(PROFILE).engine
    assert cfg.base == "origin/main"
    assert with_base(cfg, "q-parent-sha").base == "q-parent-sha"
    assert with_base(cfg, None) is cfg and with_base(cfg, "") is cfg


def test_a_receipt_made_at_the_queue_parent_is_found_there_and_not_at_the_base_branch():
    git, stores, engine = world()
    made = memo_at(git, stores, engine, "q-parent-sha")
    check = made.checks[CheckId("suite")]
    key = made.key(check)
    assert key is not None
    made.run_id = "queue-gate"
    made.remember(key, CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=0, status="passed"), 1, "")
    assert memo_at(git, stores, engine, "q-parent-sha").result(check) is not None
    assert memo_at(git, stores, engine, "main-sha").result(check) is None
    assert key.base == "q-parent-sha"
