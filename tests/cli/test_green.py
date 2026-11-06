"""`tl green`: a pass or planned skip for exactly that tree and base, with its reason; reads the result store and writes nothing."""
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit

# isort: split
from support.memstores import fake_stores

from taskloop.adapters import check_files
from taskloop.app.checks.cache import InputKeys, RunMemo, key_digest, plan_digest
from taskloop.cli import green
from taskloop.contracts.checks import Check, CheckResult, PassRecord, Verdict
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.real import real_stores


class RepoGit(ScriptedGit):
    """Every path is a worktree of the repo whose origin is `url`."""

    url = "git@example.com:o/repo.git"

    profile = json.dumps({"engine": {"checks": [{"id": "unit", "argv": ["x"], "run": "gate"}]}})

    def show(self, d, rev, path):
        return self.profile

    def ls_tree(self, d, rev, *paths, recursive=False):
        return []

    def config_get(self, d: str, key: str) -> str:
        return self.url if d.startswith("/repo") else "git@example.com:o/other.git"


def run(step="unit", tree="T1", base="B1", status: Verdict = "passed"):
    keys = InputKeys(RepoGit(), "/repo", TreeSha(tree))
    keys.files = {}
    memo = RunMemo(fake_stores(), "repo", keys, BaseSha(base), {"TL_SLOT": "check"})
    key = memo.key(Check(id=CheckId(step), cmd="x"))
    assert key is not None
    res = CheckResult(id=CheckId(step), cmd="x", group="tests", exit=0 if status == "passed" else 1, status=status)
    return PassRecord(key=key, result=res, tree=TreeSha(tree), base=BaseSha(base))


class GreenCase(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.git = RepoGit()
        self.out: list[str] = []

    def ask(self, step="unit", tree="T1", base="B1", repo="/repo"):
        a = Namespace(step=step, repo=repo, tree=tree, base=base)
        return green.cmd_green(a, self.cfg, self.git, self.out.append)

    def store(self, *recs):
        repo = check_files.repo_key(self.git, "/repo")
        for r in recs:
            real_stores(self.cfg).results(repo, r.key.check).of(key_digest(r.key)).write(r)

    def test_no_store_is_not_green(self):
        assert self.ask() == 1
        assert self.out == ["not green: unit tree T1 base B1"]

    def test_pass_for_that_tree_and_base_is_green(self):
        self.store(run())
        assert self.ask() == 0
        assert self.out == ["green: unit tree T1 base B1 (passed)"]

    def test_a_planned_skip_is_green_and_prints_its_reason(self):
        rec = run(status="skipped")
        self.store(rec.replace(result=rec.result.replace(exit=None, planned=True, why="no change under ui/**")))
        assert self.ask() == 0
        assert self.out == ["green: unit tree T1 base B1 (skipped-by-plan: no change under ui/**)"]
        assert self.ask(tree="T2") == 1
        assert self.ask(base="B2") == 1

    def test_a_failed_first_skip_is_never_green(self):
        rec = run(status="skipped")
        self.store(rec.replace(result=rec.result.replace(exit=None, why="static failed first")))
        assert self.ask() == 1

    def test_judged_config_selects_the_plan_digest_and_an_invalid_profile_refuses_passes(self):
        cmd = ["repo-plan", "steps", "--json"]
        rec = run(status="skipped")
        self.store(rec.replace(key=rec.key.replace(plan=plan_digest(cmd)),
                               result=rec.result.replace(exit=None, planned=True, why="no relevant paths")))
        with mock.patch.object(self.git, "config_get", return_value=self.git.url):
            for argv, expected in ((cmd, 0), (["repo-plan", "other"], 1), (None, 1), (cmd, 0)):
                with self.subTest(argv=argv):
                    self.git.profile = json.dumps({"engine": {"plan_cmd": argv, "checks": [
                        {"id": "unit", "argv": ["x"], "run": "gate"}]}})
                    assert self.ask(repo=self.tmp.name) == expected
            self.git.profile = "invalid json"
            assert self.ask(repo=self.tmp.name) == 1
            self.store(run())
            assert self.ask(repo=self.tmp.name) == 1

    def test_metadata_cannot_relabel_a_whole_tree_pass_for_another_subject(self):
        self.store(run().replace(tree=TreeSha("T2"), base=BaseSha("B2")))  # metadata cannot change the key's subject
        assert self.ask(tree="T2", base="B2") == 1
        assert self.ask() == 0

    def test_changed_argv_or_environment_cannot_authorize_delivery(self):
        self.store(run())
        for change in ({"argv": ["other"]}, {"env": {"MODE": "other"}}):
            with self.subTest(change=change):
                self.git.profile = json.dumps({"engine": {"checks": [{"id": "unit", "argv": ["x"], **change}]}})
                assert self.ask() == 1

    def test_other_step_tree_base_or_repo_is_not_green(self):
        self.store(run())
        assert self.ask(step="lint") == 1
        assert self.ask(tree="T2") == 1
        assert self.ask(base="B2") == 1
        assert self.ask(repo="/elsewhere") == 1

    def test_a_remembered_non_pass_is_not_green(self):
        self.store(run(status="failed"))
        assert self.ask() == 1

    def test_asking_writes_nothing(self):
        self.store(run())
        before = sorted(p for p in Path(self.tmp.name).rglob("*"))
        self.ask()
        self.ask(repo="/elsewhere")
        assert sorted(Path(self.tmp.name).rglob("*")) == before
