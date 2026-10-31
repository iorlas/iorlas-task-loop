"""`tl land-stack`: a stack of branches or PRs is delivered in order, each PR's own merge commit recorded, under the land lock, every
command a row of one run, and the first failure ends it with its own exit code and touches nothing later."""
import contextlib
import io
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim
from support.logs import records

# isort: split
from taskloop.adapters import landlock, locks
from taskloop.app.land.cmds import Cmds
from taskloop.app.land.forge import Forge
from taskloop.app.land.stack import MODE, Stack
from taskloop.cli.land_stack import cmd_land_stack
from taskloop.contracts.forge import StackItem
from taskloop.contracts.gitfacts import LogRow, Ref
from taskloop.contracts.identity import Identity
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush
from taskloop.contracts.slots import Checkout, SlotGitError
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog

OID: dict[str, str] = {"task/a": "a" * 40, "task/b": "b" * 40}


class RepoGit(ScriptedGit):
    """A repo of local branches (name -> oid) and the worktrees that have some out."""

    def __init__(self, local: dict[str, str], sim: ForgeSim) -> None:
        super().__init__()
        self.local, self.worktrees, self.deleted, self.sim = dict(local), {}, [], sim

    def ask(self, *argv):
        """The remote's answer to a git command, as the sim gives it; git's refusal is a SlotGitError."""
        ran = self.sim.run(["git", *argv])
        if ran.exit:
            raise SlotGitError(ran.err)
        return ran.out

    def push(self, d, remote, refspec):
        self.ask("push", remote, refspec)

    def ls_remote(self, d, remote, *patterns):
        return [Ref(name=ln.split("\t")[1], oid=ln.split("\t")[0]) for ln in self.ask("ls-remote", remote, *patterns).splitlines()]

    def fetch(self, d):
        self.ask("fetch", "origin")

    def rev_parse(self, d, rev):
        return self.local.get(rev.removeprefix("refs/heads/"), "")

    def log(self, d, include, exclude=None, limit=0, grep=""):
        return [LogRow(oid=include[0], time=0, subject="subject of " + include[0][:4])]

    def remote_url(self, d, remote):
        return "git@example.com:o/r.git"

    def checkouts(self, d):
        return [Checkout(path="/repo", branch="main", main=True),
                *(Checkout(path=p, branch=b, main=False) for b, p in self.worktrees.items())]

    def remove_worktree_why(self, repo, path):
        self.worktrees = {b: p for b, p in self.worktrees.items() if p != path}
        return ""

    def delete_branch_at(self, d, branch, oid):
        if self.local.get(branch) != oid:
            raise SlotGitError("moved")
        del self.local[branch]
        self.deleted.append(branch)


class StackCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.sim = ForgeSim()
        self.git = RepoGit(OID, self.sim)
        self.recorded: list[tuple[str, str, bool]] = []
        self.rc_of_record = 0
        self.synced = DoltPush(0, "")

    def locked_now(self) -> bool:
        path = landlock.land_lock_path(self.cfg, "git@example.com:o/r.git")
        try:
            with locks.hold_path(path, "probe", timeout=0):
                return False
        except LockTimeout:
            return True

    def record(self, bead, sha):
        self.recorded.append((bead, sha, self.locked_now()))
        return self.rc_of_record

    def deliver(self, *items, **kw):
        run = "land-stack-20261031-100000"
        log = RunLog(real_stores(self.cfg).run_log(run), run_id=run, host="h")
        cmds = Cmds(self.sim, log, "/repo")
        lock = landlock.land_lock_path(self.cfg, "git@example.com:o/r.git")
        forge = Forge(cmds, self.git, "/repo", "main")
        stack = Stack(forge, cmds, log, self.git, "/repo", lock, self.record, lambda: self.synced, "tl-me", "sess-1", **kw)
        self.rc = stack.run(list(items))
        self.rows = records(self.cfg.engine_log(run))
        return self.rc

    def kinds(self, *kinds):
        return [r for r in self.rows if r["kind"] in kinds]


class Delivery(StackCase):
    def test_a_stack_lands_in_order_each_with_its_own_merge_sha_recorded_under_the_lock(self):
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"))
        self.assertEqual(rc, 0)
        self.assertEqual([(b, s[:6]) for b, s, _ in self.recorded], [("a", "merge1"), ("b", "merge2")])
        self.assertTrue(all(held for _, _, held in self.recorded))
        self.assertEqual(len(self.sim.ran("gh pr merge")), 2)
        self.assertTrue(self.sim.ran("gh pr merge 1")[0].endswith("--match-head-commit " + "a" * 40))
        self.assertEqual(self.git.deleted, ["task/a", "task/b"])

    def test_every_command_is_a_row_of_the_run_and_the_run_is_labelled(self):
        self.deliver(StackItem(branch="task/a"))
        start = self.kinds("run_start")[0]
        self.assertEqual((start["mode"], start["owner"], start["session"]), (MODE, "tl-me", "sess-1"))
        starts = self.kinds("cmd_start")
        self.assertGreaterEqual(len(starts), len(self.sim.calls))
        self.assertEqual({r["run_id"] for r in self.rows}, {"land-stack-20261031-100000"})
        self.assertEqual([r["text"] for r in starts][: len(self.sim.calls)], self.sim.calls)
        self.assertEqual(len(starts), len(self.kinds("cmd_end")))
        self.assertEqual(self.kinds("close")[0]["outcome"], "landed")
        self.assertEqual(self.kinds("lock")[0]["what"], "land")
        self.assertEqual([r["bead"] for r in self.kinds("step_start")], ["a"])

    def test_a_failing_merge_stops_with_its_exit_code_and_leaves_later_prs_untouched(self):
        self.sim.fail["gh pr merge"] = 7
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"))
        self.assertEqual(rc, 7)
        self.assertEqual(self.recorded, [])
        self.assertNotIn("task/b", self.sim.remote)
        self.assertEqual(self.sim.ran("gh pr create").__len__(), 1)
        self.assertEqual(self.kinds("close")[0]["outcome"], "failed")
        self.assertEqual(self.git.deleted, [])

    def test_a_failure_in_the_second_keeps_the_first_landed_and_the_third_untouched(self):
        self.git.local["task/c"] = "c" * 40
        self.sim.fail["gh pr merge 2"] = 9
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"), StackItem(branch="task/c"))
        self.assertEqual(rc, 9)
        self.assertEqual([b for b, _, _ in self.recorded], ["a"])
        self.assertNotIn("task/c", self.sim.remote)
        self.assertEqual(len(self.sim.ran("bd")), 0)

    def test_a_remote_that_does_not_answer_stops_the_run_before_a_pr_is_opened(self):
        self.sim.fail["git ls-remote"] = 2
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertEqual(self.sim.ran("gh pr create"), [])

    def test_the_old_pr_is_closed_only_after_its_replacement_merged(self):
        self.sim.pr(5, "old", "o" * 40)
        self.deliver(StackItem(branch="task/a", supersedes=5))
        calls = self.sim.calls
        self.assertLess(calls.index(self.sim.ran("gh pr merge")[0]), calls.index(self.sim.ran("gh pr close 5")[0]))
        self.assertEqual(self.sim.prs[5]["state"], "CLOSED")

    def test_the_old_pr_stays_open_when_the_replacement_fails(self):
        self.sim.pr(5, "old", "o" * 40)
        self.sim.fail["gh pr merge"] = 1
        self.deliver(StackItem(branch="task/a", supersedes=5))
        self.assertEqual(self.sim.prs[5]["state"], "OPEN")
        self.assertEqual(self.sim.ran("gh pr close"), [])

    def test_an_existing_pr_is_merged_without_a_push_or_a_new_pr(self):
        self.sim.pr(3, "task/a", OID["task/a"])
        rc = self.deliver(StackItem(pr=3))
        self.assertEqual(rc, 0)
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr create"), [])
        self.assertEqual([(b, s[:6]) for b, s, _ in self.recorded], [("a", "merge3")])

    def test_a_branch_the_forge_deleted_on_merge_is_no_failure(self):
        self.sim.delete_on_merge = True
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertNotIn("task/a", self.sim.remote)

    def test_a_rerun_after_a_merge_records_it_without_merging_again(self):
        self.deliver(StackItem(branch="task/a"))
        self.git.local["task/a"] = OID["task/a"]
        self.sim.calls.clear()
        self.recorded.clear()
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual(self.sim.ran("gh pr merge"), [])
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(len(self.recorded), 1)

    def test_a_refused_record_stops_with_its_code_before_the_next_pr(self):
        self.rc_of_record = 3
        self.assertEqual(self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")), 3)
        self.assertEqual(self.sim.ran("gh pr merge 2"), [])

    def test_a_local_branch_that_moved_is_kept_with_its_worktree(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.sim.remote["task/a"] = OID["task/a"]
        orig = self.git.rev_parse
        calls = []

        def moved(d, rev):
            calls.append(rev)
            return "f" * 40 if len(calls) > 1 else orig(d, rev)

        self.git.rev_parse = moved
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual(self.git.deleted, [])
        self.assertEqual(self.git.worktrees, {"task/a": "/wt/a"})

    def test_a_clean_worktree_goes_with_its_landed_branch(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.deliver(StackItem(branch="task/a"))
        self.assertEqual(self.git.worktrees, {})
        self.assertEqual(self.git.deleted, ["task/a"])

    def test_bd_sync_failure_ends_the_run_with_its_code_after_the_lands(self):
        self.synced = DoltPush(2, "conflict")
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 2)
        self.assertEqual(len(self.recorded), 1)
        self.assertEqual(self.kinds("close")[0]["outcome"], "failed")

    def test_gh_words_that_are_no_pr_stop_the_run(self):
        self.sim.say["gh pr list"] = '[{"number": "x"}]'
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertEqual(self.sim.ran("git push"), [])

    def test_a_missing_gh_is_exit_127(self):
        self.sim.missing = True
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 127)


class Verb(StackCase):
    def test_the_verb_makes_a_run_the_board_finds_through_its_manifest(self):
        a = Namespace(items=["task/a", "task/b"], repo="/repo", base="main", method="squash", bead=["task/b=tl-b"], supersede=[],
                      wait_min=None)
        store = SimpleNamespace(dolt_push=lambda: DoltPush(0, ""))
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_land_stack(a, who, self.git, self.sim, store, self.record)
        self.assertEqual(rc, 0)
        (bundle,) = RunLocator(self.cfg).runs()
        self.assertIsNotNone(bundle.manifest.ended)
        rows = records(bundle.log)
        self.assertEqual(rows[0]["mode"], MODE)
        self.assertEqual([b for b, _, _ in self.recorded], ["a", "tl-b"])


if __name__ == "__main__":
    unittest.main()
