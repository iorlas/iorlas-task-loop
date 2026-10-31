"""`tl green`: a pass or planned skip for exactly that tree and base, with its reason; reads the result store and writes nothing."""
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit

# isort: split
from taskloop.adapters import check_files
from taskloop.app.checks.cache import key_digest, plan_digest
from taskloop.cli import green
from taskloop.contracts.checks import CheckResult, PassRecord, Verdict
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.stores.real import real_stores


class RepoGit(ScriptedGit):
    """Every path is a worktree of the repo whose origin is `url`."""

    url = "git@example.com:o/repo.git"

    def config_get(self, d: str, key: str) -> str:
        return self.url if d.startswith("/repo") else "git@example.com:o/other.git"


def run(step="unit", tree="T1", base="B1", status: Verdict = "passed"):
    key = RunKey(check=CheckId(step), cmd=Digest("c"), config=Digest("g"), toolchain=Digest("t"), tree=TreeSha(tree), base=BaseSha(base),
                 inputs=Digest("i"), selected=Digest(""), env=Digest("e"))
    res = CheckResult(id=CheckId(step), cmd="x", group="g", exit=0 if status == "passed" else 1, status=status)
    return PassRecord(key=key, result=res, tree=TreeSha(tree), base=BaseSha(base))


class GreenCase(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(self.ask(), 1)
        self.assertEqual(self.out, ["not green: unit tree T1 base B1"])

    def test_pass_for_that_tree_and_base_is_green(self):
        self.store(run())
        self.assertEqual(self.ask(), 0)
        self.assertEqual(self.out, ["green: unit tree T1 base B1 (passed)"])

    def test_a_planned_skip_is_green_and_prints_its_reason(self):
        rec = run(status="skipped")
        self.store(rec.replace(result=rec.result.replace(exit=None, planned=True, why="no change under ui/**")))
        self.assertEqual(self.ask(), 0)
        self.assertEqual(self.out, ["green: unit tree T1 base B1 (skipped-by-plan: no change under ui/**)"])
        self.assertEqual(self.ask(tree="T2"), 1)
        self.assertEqual(self.ask(base="B2"), 1)

    def test_a_failed_first_skip_is_never_green(self):
        rec = run(status="skipped")
        self.store(rec.replace(result=rec.result.replace(exit=None, why="static failed first")))
        self.assertEqual(self.ask(), 1)

    def test_repo_config_selects_the_plan_digest_for_skips_and_leaves_passes_green(self):
        cmd = ["repo-plan", "steps", "--json"]
        rec = run(status="skipped")
        self.store(rec.replace(key=rec.key.replace(plan=plan_digest(cmd)),
                               result=rec.result.replace(exit=None, planned=True, why="no relevant paths")))
        profile = Path(self.tmp.name) / ".task-loop.json"
        with mock.patch.object(self.git, "config_get", return_value=self.git.url):
            for argv, expected in ((cmd, 0), (["repo-plan", "other"], 1), (None, 1), (cmd, 0)):
                with self.subTest(argv=argv):
                    profile.write_text(json.dumps({"engine": {"plan_cmd": argv}}))
                    self.assertEqual(self.ask(repo=self.tmp.name), expected)
            profile.write_text("invalid json")
            self.assertEqual(self.ask(repo=self.tmp.name), 1)
            self.store(run())
            self.assertEqual(self.ask(repo=self.tmp.name), 0)

    def test_a_pass_served_for_another_tree_and_base_is_green_for_them(self):
        self.store(run().replace(tree=TreeSha("T2"), base=BaseSha("B2")))  # the record of a reuse: true for T2 on B2 now
        self.assertEqual(self.ask(tree="T2", base="B2"), 0)
        self.assertEqual(self.ask(), 1)

    def test_other_step_tree_base_or_repo_is_not_green(self):
        self.store(run())
        self.assertEqual(self.ask(step="lint"), 1)
        self.assertEqual(self.ask(tree="T2"), 1)
        self.assertEqual(self.ask(base="B2"), 1)
        self.assertEqual(self.ask(repo="/elsewhere"), 1)

    def test_a_remembered_non_pass_is_not_green(self):
        self.store(run(status="failed"))
        self.assertEqual(self.ask(), 1)

    def test_asking_writes_nothing(self):
        self.store(run())
        before = sorted(p for p in Path(self.tmp.name).rglob("*"))
        self.ask()
        self.ask(repo="/elsewhere")
        self.assertEqual(sorted(Path(self.tmp.name).rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
