"""`tl land-stack`: a stack of branches or PRs is delivered in order, each PR's own merge commit recorded, under the land lock, every
command a row of one run, and the first failure ends it with its own exit code and touches nothing later."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim
from support.logs import records

# isort: split
from taskloop.adapters import check_files, landlock, locks
from taskloop.app.checks.cache import InputKeys, RunMemo, plan_digest
from taskloop.app.land.cmds import Cmds
from taskloop.app.land.forge import Forge
from taskloop.app.land.stack import MODE, Stack
from taskloop.app.land.stackgate import StackGate
from taskloop.app.track.verbs import trace
from taskloop.app.wire import closeguard
from taskloop.cli.land_stack import cmd_land_stack
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import Check, CheckResult
from taskloop.contracts.env import Env
from taskloop.contracts.forge import StackItem
from taskloop.contracts.gitfacts import LogRow, Ref, TreeEntry
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, CheckId, TreeSha
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush
from taskloop.contracts.runkey import BaseSha
from taskloop.contracts.slots import Checkout, SlotGitError
from taskloop.stores.memory import fake_stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog

OID: dict[str, str] = {"task/a": "a" * 40, "task/b": "b" * 40}


class RepoGit(ScriptedGit):
    """A repo of local branches (name -> oid) and the worktrees that have some out."""

    def __init__(self, local: dict[str, str], sim: ForgeSim) -> None:
        super().__init__()
        self.local, self.worktrees, self.deleted, self.sim = dict(local), {}, [], sim
        self.fetched, self.heads, self.dirty_at = set(), {}, set()  # oids fetched in, HEAD of a path, dirty paths
        self.profiles: dict[str, str] = {}

    def ls_tree(self, d, rev, *paths, recursive=False):
        self.seen("ls_tree", rev, *paths)
        return [TreeEntry(mode="100644", kind="blob", oid="profile", path=".task-loop.json")] if rev in self.profiles else []

    def show(self, d, rev, path):
        self.seen("show", rev, path)
        return self.profiles[rev]

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
        self.fetched |= set(self.sim.remote.values())

    def rev_parse(self, d, rev):
        if rev.endswith("^{tree}"):
            return "tree-" + rev[:6]
        if rev in self.fetched or rev == "origin/main":
            return rev
        if rev == "HEAD":
            return self.heads.get(d, "")
        return self.local.get(rev.removeprefix("refs/heads/"), "")

    def config_get(self, d, key):
        return "git@example.com:o/r.git"

    def common_dir(self, d):
        return "/repo/.git"

    def dirty(self, d):
        return d in self.dirty_at

    def log(self, d, include, exclude=None, limit=0, grep=""):
        return [LogRow(oid=include[0], time=0, subject="subject of " + include[0][:4])]

    def remote_url(self, d, remote):
        return "git@example.com:o/r.git"

    def is_ancestor(self, d, a, b):
        return True

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
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.sim = ForgeSim()
        self.git = RepoGit(OID, self.sim)
        self.recorded: list[tuple[str, str, bool]] = []
        self.rc_of_record = 0
        self.synced = DoltPush(0, "")
        self.beads: list[str] = []

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
        cmds = Cmds(self.sim, log, str(self.repo))
        lock = landlock.land_lock_path(self.cfg, "git@example.com:o/r.git")
        forge = Forge(cmds, self.git, str(self.repo), "main")
        gate = StackGate(cmds, self.git, real_stores(self.cfg), str(self.repo), "origin/main", ["tl"])
        stack = Stack(forge, cmds, log, self.git, str(self.repo), lock, self.record, lambda: self.synced, "tl-me", "sess-1", gate,
                      FakeBeads(actor="tl-me"), named=self.beads.append, **kw)
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
        self.assertEqual([r["text"] for r in starts if r["text"] in self.sim.calls], self.sim.calls)
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


class RemoteOnly(StackCase):
    def test_a_branch_only_origin_has_is_fetched_and_delivered(self):
        del self.git.local["task/b"]
        self.sim.remote["task/b"] = OID["task/b"]
        self.assertEqual(self.deliver(StackItem(branch="task/b")), 0)
        self.assertEqual(self.sim.ran("git ls-remote origin refs/heads/task/b")[:1], ["git ls-remote origin refs/heads/task/b"])
        self.assertTrue(self.sim.ran("git fetch origin"))
        self.assertEqual([b for b, _, _ in self.recorded], ["b"])

    def test_a_name_that_exists_nowhere_is_refused_naming_the_commands(self):
        self.assertEqual(self.deliver(StackItem(branch="task/zzz")), 1)
        why = self.kinds("warn")[0]["text"]
        self.assertIn("git ls-remote origin refs/heads/task/zzz", why)
        self.assertIn("git rev-parse --verify refs/heads/task/zzz", why)
        self.assertEqual(self.sim.ran("gh pr create"), [])

    def test_a_failing_fetch_names_the_command(self):
        del self.git.local["task/b"]
        self.sim.remote["task/b"] = OID["task/b"]
        self.sim.fail["git fetch"] = 4
        self.assertEqual(self.deliver(StackItem(branch="task/b")), 1)
        self.assertIn("git fetch origin", self.kinds("warn")[0]["text"])


class StoredGate(StackCase):
    def test_delivery_compares_planned_skips_to_the_judged_commits_producer(self):
        stores = real_stores(self.cfg)
        tree, base = TreeSha("tree-" + OID["task/a"][:6]), BaseSha("origin/main")
        keys = InputKeys(self.git, str(self.repo), tree)
        keys.files = {}
        memo = RunMemo(stores, check_files.repo_key(self.git, str(self.repo)), keys, base, {})
        check = Check(id=CheckId("lint"), cmd="true", when=["src/**"])
        cmd = ["repo-plan", "steps", "--json"]
        skip = CheckResult.skipped(check, "no change under src/**").replace(planned=True)
        memo.remember(memo.planned_key(check, plan_digest(cmd)), skip, 1, "")
        profile = {"engine": {"plan_cmd": ["old-plan"], "checks": [{"id": "lint", "argv": ["true"], "run": "gate"}]}}
        (self.repo / ".task-loop.json").write_text(json.dumps(profile))
        self.git.profiles[OID["task/a"]] = json.dumps(profile)
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr merge"), [])
        profile["engine"]["plan_cmd"] = cmd
        self.git.profiles[OID["task/a"]] = json.dumps(profile)
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual(self.sim.ran("tl check"), [])

    def test_a_stored_planned_skip_satisfies_stackgate_only_for_its_tree_and_base(self):
        stores = fake_stores()
        tree, base = TreeSha("tree-a"), BaseSha("base-a")
        keys = InputKeys(self.git, str(self.repo), tree)
        keys.files = {}
        memo = RunMemo(stores, check_files.repo_key(self.git, str(self.repo)), keys, base, {})
        check = Check(id=CheckId("coverage"), cmd="coverage", when=["src/**"])
        skip = CheckResult.skipped(check, "no change under src/**").replace(planned=True)
        memo.remember(memo.planned_key(check), skip, 1, "")
        log = RunLog(stores.run_log("gate-test"), run_id="gate-test", host="h")
        gate = StackGate(Cmds(self.sim, log, str(self.repo)), self.git, stores, str(self.repo), "origin/main", ["tl"])
        self.assertEqual(gate.red([check.id], tree, base, plan_digest(None)), [])
        self.assertEqual(gate.red([check.id], "other-tree", base, plan_digest(None)), [check.id])
        self.assertEqual(gate.red([check.id], tree, "other-base", plan_digest(None)), [check.id])
        self.assertEqual(gate.red([CheckId("never-ran")], tree, base, plan_digest(None)), ["never-ran"])
        memo.remember(memo.planned_key(check), skip.replace(planned=False, why="static failed first"), 2, "")
        self.assertEqual(gate.red([check.id], tree, base, plan_digest(None)), [])  # invalid skip cannot overwrite a satisfied decision
        cmd = ["repo-plan", "steps", "--json"]
        memo.remember(memo.planned_key(check, plan_digest(cmd)), skip, 3, "")
        profile = self.repo / ".task-loop.json"
        profile.write_text(json.dumps({"engine": {"plan_cmd": ["stale-plan"]}}))
        for argv, red in ((cmd, []), (["repo-plan", "changed"], [check.id]), (cmd, [])):
            with self.subTest(argv=argv):
                self.git.profiles[OID["task/a"]] = json.dumps({"engine": {"plan_cmd": argv}})
                engine = gate.profile(OID["task/a"])
                assert engine is not None
                self.assertEqual(gate.red([check.id], tree, base, plan_digest(engine.plan_cmd)), red)


class GateCase(StackCase):
    def setUp(self):
        super().setUp()
        profile = '{"engine": {"checks": [{"id": "lint", "argv": ["true"], "run": "gate"}]}}'
        self.git.profiles = dict.fromkeys(OID.values(), profile)
        self.green: set[str] = set()  # trees the store holds a pass for
        patch = mock.patch("taskloop.app.land.stackgate.is_green", lambda st, repo, step, tree, base, plan: tree in self.green)
        patch.start()
        self.addCleanup(patch.stop)


class Gated(GateCase):
    def test_a_green_tree_is_delivered_without_a_run(self):
        self.green.add("tree-" + OID["task/a"][:6])
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual(self.sim.ran("tl check"), [])

    def test_a_red_tree_with_no_worktree_is_refused_with_the_command_and_nothing_pushed(self):
        self.assertEqual(self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")), 1)
        self.assertIn("tl check --repo", self.kinds("warn")[0]["text"])
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr"), self.sim.ran("gh pr list"))

    def test_a_red_tree_in_a_clean_worktree_is_gated_then_delivered(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        real_run = self.sim.run

        def run(argv, **kw):
            if argv[:2] == ["tl", "check"]:
                self.green.add("tree-" + OID["task/a"][:6])
            return real_run(argv, **kw)

        self.sim.run = run
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual(self.sim.ran("tl check --repo /wt/a"), ["tl check --repo /wt/a"])

    def test_a_gate_that_stays_red_stops_with_its_exit_code_and_later_items_untouched(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        self.sim.fail["tl check"] = 6
        self.assertEqual(self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")), 6)
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertIn("tl check --repo /wt/a", self.kinds("warn")[0]["text"])

    def test_a_dirty_worktree_is_not_gated(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        self.git.dirty_at.add("/wt/a")
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertEqual(self.sim.ran("tl check"), [])

    def test_a_repo_without_a_gate_step_passes(self):
        self.git.profiles[OID["task/a"]] = '{"engine": {"checks": [{"id": "x", "argv": ["true"], "run": "stage"}]}}'
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)

    def test_a_stale_checkout_cannot_require_coverage_removed_by_the_judged_commit(self):
        (self.repo / ".task-loop.json").write_text(
            '{"engine": {"checks": [{"id": "coverage", "argv": ["true"], "run": "gate"}]}}')
        with mock.patch("taskloop.app.land.stackgate.is_green", return_value=True) as green:
            self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)
        self.assertEqual([call.args[2] for call in green.call_args_list], ["lint"])
        self.assertTrue(self.git.ran("show", OID["task/a"], ".task-loop.json"))

    def test_a_check_added_by_the_judged_commit_is_required(self):
        (self.repo / ".task-loop.json").write_text('{"engine": {"checks": []}}')
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertIn("not green for lint", self.kinds("warn")[0]["text"])
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr merge"), [])

    def test_an_absent_profile_at_the_judged_commit_has_no_gate(self):
        (self.repo / ".task-loop.json").write_text(self.git.profiles.pop(OID["task/a"]))
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 0)

    def test_an_invalid_judged_profile_stops_before_push_or_merge(self):
        self.git.profiles[OID["task/a"]] = "{"
        self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertIn(OID["task/a"] + ":.task-loop.json", self.kinds("warn")[0]["text"])
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr merge"), [])

    def test_a_git_profile_read_failure_cannot_bypass_the_gate(self):
        with mock.patch.object(self.git, "show", side_effect=SlotGitError("cannot read object")):
            self.assertEqual(self.deliver(StackItem(branch="task/a")), 1)
        self.assertIn("cannot read object", self.kinds("warn")[0]["text"])
        self.assertEqual(self.sim.ran("git push"), [])
        self.assertEqual(self.sim.ran("gh pr merge"), [])


class Verb(StackCase):
    def test_an_unknown_explicit_bead_stops_the_whole_stack_before_push_or_merge(self):
        who = Identity(actor="tl-me", home=self.tmp.name, session="s")
        for items, beads in ((["task/a", "task/b"], ["task/b=missing-bead"]), (["293"], ["293=missing-bead"])):
            with self.subTest(items=items):
                self.assertNotEqual(self.verb(items, beads, who), 0)
                self.assertIn("unknown bead missing-bead", self.output)
                self.assertEqual(self.sim.ran("git push"), [])
                self.assertEqual(self.sim.ran("gh pr merge"), [])
        for bundle in RunLocator(who.config).runs():
            self.assertEqual(bundle.manifest.state.value, "failed")
            self.assertIn("missing-bead", bundle.manifest.reason)
            close = [r for r in records(bundle.log) if r["kind"] == "close"][-1]
            self.assertEqual(close["outcome"], "failed")
            self.assertIn("missing-bead", close["why"])

    def test_the_verb_makes_a_run_the_board_finds_through_its_manifest(self):
        a = Namespace(items=["task/a", "task/b"], repo=str(self.repo), base="main", method="squash", bead=["task/b=tl-b"], supersede=[],
                      wait_min=None)
        store = self.bd("a", "tl-b")
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_land_stack(a, who, self.git, self.sim, store, ["tl"])
        self.assertEqual(rc, 0)
        (bundle,) = RunLocator(self.cfg).runs()
        self.assertIsNotNone(bundle.manifest.ended)
        rows = records(bundle.log)
        self.assertEqual(rows[0]["mode"], MODE)
        self.assertTrue(all(closeguard.has_land(who, BeadId(b)) for b in ("a", "tl-b")))
        m = bundle.manifest
        self.assertEqual((m.mode, m.owner, m.session, m.bead, m.beads), (MODE, "tl-me", "sess-1", "a", ("tl-b",)))
        self.assertEqual(m.state.value, "done")
        self.assertTrue(any(r["kind"] == "cmd_start" and r["text"].startswith("git push") for r in rows))
        self.assertTrue(any(r["kind"] == "cmd_start" and r["text"].startswith("gh pr merge") for r in rows))

    def bd(self, *beads):
        store = FakeBeads(actor="tl-me")
        store.dolt_push = lambda: DoltPush(0, "")  # type: ignore[method-assign]
        for b in beads:
            store.beads[BeadId(b)] = Bead(id=BeadId(b), title="t", status="open", issue_type="task")
        return store

    def verb(self, items, bead, who, store=None):
        a = Namespace(items=items, repo=str(self.repo), base="main", method="squash", bead=bead, supersede=[], wait_min=None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_land_stack(a, who, self.git, self.sim, store or self.bd("lifesim-fvit"), ["tl"])
        self.output = out.getvalue()
        return rc

    def test_a_pr_number_with_a_bead_shows_its_landing_in_tl_trace_and_the_manifest(self):
        root = Path(self.tmp.name) / "xdg"
        who = Identity(actor="tl-me", home=str(root / "task-loop"), session="sess-1")
        self.sim.pr(293, "task/a", OID["task/a"])
        self.assertEqual(self.verb(["293"], ["293=lifesim-fvit"], who), 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            trace(BeadId("lifesim-fvit"), 0, False, Env(vars={"XDG_CONFIG_HOME": str(root)}))
        self.assertIn("lifesim-fvit  landed", out.getvalue())
        self.assertIn("landed " + "merge293"[:12], out.getvalue())
        (bundle,) = RunLocator(who.config).runs()
        self.assertEqual(bundle.manifest.bead, "lifesim-fvit")

    def test_after_a_pr_number_land_the_bead_closes_with_no_extra_step(self):
        who = Identity(actor="tl-me", home=str(Path(self.tmp.name) / "xdg2"), session="sess-1")
        store = self.bd("lifesim-fvit")
        self.sim.pr(294, "task/a", OID["task/a"])
        RunLocator(who.config).create(str(self.repo), "lifesim-fvit", 1.0)  # the bead has an engine run, and no land yet
        guard = closeguard.guard_for(who, store, self.git, str(self.repo))
        self.assertIn("no land on record", guard(BeadId("lifesim-fvit"), "done"))
        self.assertEqual(self.verb(["294"], ["294=lifesim-fvit"], who, store), 0)
        self.assertEqual(guard(BeadId("lifesim-fvit"), "done"), "")

    def test_a_bead_for_an_item_that_is_not_given_is_refused_naming_both(self):
        who = Identity(actor="tl-me", home=self.tmp.name, session="s")
        with self.assertRaises(SystemExit) as e:
            self.verb(["293"], ["task/x=lifesim-okrs"], who)
        self.assertIn("task/x", str(e.exception))
        self.assertIn("293", str(e.exception))
        self.assertEqual(self.sim.calls, [])


if __name__ == "__main__":
    unittest.main()
