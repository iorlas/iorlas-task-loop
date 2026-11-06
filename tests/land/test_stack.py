"""`tl land-stack`: a stack of branches or PRs is delivered in order, each PR's own merge commit recorded, under the land lock, every
command a row of one run, and the first failure ends it with its own exit code and touches nothing later."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim
from support.logs import records

# isort: split
from support.memstores import fake_stores

from taskloop.adapters import check_files, landlock, locks
from taskloop.app.checks.cache import InputKeys, RunMemo, plan_digest
from taskloop.app.land.carry import Carry
from taskloop.app.land.cmds import Cmds
from taskloop.app.land.forge import Forge
from taskloop.app.land.stack import MODE, Stack
from taskloop.app.land.stackgate import StackGate
from taskloop.app.run.finish import answer
from taskloop.app.track.verbs import trace
from taskloop.app.wire import closeguard
from taskloop.cli.land_stack import cmd_land_stack
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import Check, CheckResult
from taskloop.contracts.config import load
from taskloop.contracts.env import Env
from taskloop.contracts.finish import finish_run
from taskloop.contracts.forge import StackItem
from taskloop.contracts.gitfacts import LogRow, Ref, TreeEntry
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId, CheckId, TreeSha
from taskloop.contracts.kinds import Kind
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import DoltPush
from taskloop.contracts.runkey import BaseSha
from taskloop.contracts.slots import Checkout, NotARepo, SlotGitError
from taskloop.domain import outcome as oc
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog

OID: dict[str, str] = {"task/a": "a" * 40, "task/b": "b" * 40}


class RepoGit(ScriptedGit):
    """A repo of local branches (name -> oid) and the worktrees that have some out."""

    def __init__(self, local: dict[str, str], sim: ForgeSim) -> None:
        super().__init__()
        self.local, self.worktrees, self.deleted, self.sim = dict(local), {}, [], sim
        self.fetched, self.heads, self.dirty_at, self.gone = set(), {}, set(), set()  # oids fetched in, HEAD of a path, dirty paths
        self.profiles: dict[str, str] = {}

    def ls_tree(self, d, rev, *paths, recursive=False):
        self.seen("ls_tree", rev, *paths)
        return [TreeEntry(mode="100644", kind="blob", oid=hashlib.sha256(self.profiles[rev].encode()).hexdigest(),
                          path=".task-loop.json")] if rev in self.profiles else []

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
        if d in self.gone:
            raise NotARepo(f"git rev-parse exited 128: fatal: cannot change to '{d}'")
        if rev.endswith("^{tree}"):
            return "tree-" + rev[:6]
        if rev in self.fetched or rev == "origin/main":
            return rev
        if rev == "HEAD":
            return self.heads.get(d, "")
        return self.local.get(rev.removeprefix("refs/heads/"), "")

    def config_get(self, d, key):
        return "git@example.com:o/r.git"

    def common_dir(self, d) -> str:
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

    def add_worktree(self, repo, path, ref):
        self.seen("add_worktree", path, ref)
        self.heads[path] = ref

    def remove_worktree_force(self, repo, path):
        self.seen("remove_worktree_force", path)

    def remove_worktree_why(self, repo, path):
        self.worktrees = {b: p for b, p in self.worktrees.items() if p != path}
        return ""

    def delete_branch_at(self, d, branch, oid):
        if self.local.get(branch) != oid:
            raise SlotGitError("moved")
        del self.local[branch]
        self.deleted.append(branch)


class StackCase(Case):
    def setup_method(self):
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
        run = RunLocator(self.cfg).create(str(self.repo), "", 100.0, mode=MODE).run
        log = RunLog(real_stores(self.cfg).run_log(run), run_id=run, host="h")
        cmds = Cmds(self.sim, log, str(self.repo), self.cfg.run_dir(run))
        lock = landlock.land_lock_path(self.cfg, "git@example.com:o/r.git")
        forge = Forge(cmds, self.git, str(self.repo), "main")
        gate = StackGate(cmds, self.git, real_stores(self.cfg), str(self.repo), "origin/main", ["tl"])
        stack = Stack(forge, cmds, log, self.git, str(self.repo), lock, self.record, lambda: self.synced, "tl-me", "sess-1", gate,
                      FakeBeads(actor="tl-me"), named=self.beads.append, **kw)
        self.rc = stack.run(list(items))
        done = oc.make(Kind.LANDED if self.rc == 0 else Kind.FAULT_LAND,
                       f"{len(items)} delivered" if self.rc == 0 else stack.failure_reason, sha=stack.last)
        finish_run(self.cfg, run, answer(done, 200.0))
        self.rows = records(self.cfg.engine_log(run))
        return self.rc

    def kinds(self, *kinds):
        return [r for r in self.rows if r["kind"] in kinds]


class Delivery(StackCase):
    def test_a_stack_lands_in_order_each_with_its_own_merge_sha_recorded_under_the_lock(self):
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"))
        assert rc == 0
        assert [(b, s[:6]) for b, s, _ in self.recorded] == [("a", "merge1"), ("b", "merge2")]
        assert all(held for _, _, held in self.recorded)
        assert len(self.sim.ran("gh pr merge")) == 2
        assert self.sim.ran("gh pr merge 1")[0].endswith("--match-head-commit " + "a" * 40)
        assert self.git.deleted == ["task/a", "task/b"]

    def test_every_command_is_a_row_of_the_run_and_the_run_is_labelled(self):
        self.deliver(StackItem(branch="task/a"))
        start = self.kinds("run_start")[0]
        assert (start["mode"], start["owner"], start["session"]) == (MODE, "tl-me", "sess-1")
        starts = self.kinds("cmd_start")
        assert len(starts) >= len(self.sim.calls)
        assert {r["run_id"] for r in self.rows} == {start["run_id"]}
        assert [r["text"] for r in starts if r["text"] in self.sim.calls] == self.sim.calls
        assert len(starts) == len(self.kinds("cmd_end"))
        assert self.kinds("close")[0]["outcome"] == "landed"
        assert self.kinds("lock")[0]["what"] == "land"
        assert [r["bead"] for r in self.kinds("step_start")] == ["a"]

    def test_a_failing_merge_stops_with_its_exit_code_and_leaves_later_prs_untouched(self):
        self.sim.fail["gh pr merge"] = 7
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"))
        assert rc == 7
        assert self.recorded == []
        assert "task/b" not in self.sim.remote
        assert self.sim.ran("gh pr create").__len__() == 1
        assert self.kinds("close")[0]["outcome"] == "failed"
        assert self.git.deleted == []

    def test_a_failure_in_the_second_keeps_the_first_landed_and_the_third_untouched(self):
        self.git.local["task/c"] = "c" * 40
        self.sim.fail["gh pr merge 2"] = 9
        rc = self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b"), StackItem(branch="task/c"))
        assert rc == 9
        assert [b for b, _, _ in self.recorded] == ["a"]
        assert "task/c" not in self.sim.remote
        assert len(self.sim.ran("bd")) == 0

    def test_a_remote_that_does_not_answer_stops_the_run_before_a_pr_is_opened(self):
        self.sim.fail["git ls-remote"] = 2
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert self.sim.ran("gh pr create") == []

    def test_the_old_pr_is_closed_only_after_its_replacement_merged(self):
        self.sim.pr(5, "old", "o" * 40)
        self.deliver(StackItem(branch="task/a", supersedes=5))
        calls = self.sim.calls
        assert calls.index(self.sim.ran("gh pr merge")[0]) < calls.index(self.sim.ran("gh pr close 5")[0])
        assert self.sim.prs[5]["state"] == "CLOSED"

    def test_the_old_pr_stays_open_when_the_replacement_fails(self):
        self.sim.pr(5, "old", "o" * 40)
        self.sim.fail["gh pr merge"] = 1
        self.deliver(StackItem(branch="task/a", supersedes=5))
        assert self.sim.prs[5]["state"] == "OPEN"
        assert self.sim.ran("gh pr close") == []

    def test_an_existing_pr_is_merged_without_a_push_or_a_new_pr(self):
        self.sim.pr(3, "task/a", OID["task/a"])
        rc = self.deliver(StackItem(pr=3))
        assert rc == 0
        assert self.sim.ran("git push") == []
        assert self.sim.ran("gh pr create") == []
        assert [(b, s[:6]) for b, s, _ in self.recorded] == [("a", "merge3")]

    def test_a_branch_the_forge_deleted_on_merge_is_no_failure(self):
        self.sim.delete_on_merge = True
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert "task/a" not in self.sim.remote

    def test_a_rerun_after_a_merge_records_it_without_merging_again(self):
        self.deliver(StackItem(branch="task/a"))
        self.git.local["task/a"] = OID["task/a"]
        self.sim.calls.clear()
        self.recorded.clear()
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.sim.ran("gh pr merge") == []
        assert self.sim.ran("git push") == []
        assert len(self.recorded) == 1

    def test_a_refused_record_stops_with_its_code_before_the_next_pr(self):
        self.rc_of_record = 3
        assert self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")) == 3
        assert self.sim.ran("gh pr merge 2") == []

    def test_a_local_branch_that_moved_is_kept_with_its_worktree(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.sim.remote["task/a"] = OID["task/a"]
        orig = self.git.rev_parse
        calls = []

        def moved(d, rev):
            calls.append(rev)
            return "f" * 40 if len(calls) > 1 else orig(d, rev)

        self.git.rev_parse = moved
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.git.deleted == []
        assert self.git.worktrees == {"task/a": "/wt/a"}

    def test_a_clean_worktree_goes_with_its_landed_branch(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.deliver(StackItem(branch="task/a"))
        assert self.git.worktrees == {}
        assert self.git.deleted == ["task/a"]

    def test_bd_sync_failure_ends_the_run_with_its_code_after_the_lands(self):
        self.synced = DoltPush(2, "conflict")
        assert self.deliver(StackItem(branch="task/a")) == 2
        assert len(self.recorded) == 1
        assert self.kinds("close")[0]["outcome"] == "failed"

    def test_gh_words_that_are_no_pr_stop_the_run(self):
        self.sim.say["gh pr list"] = '[{"number": "x"}]'
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert self.sim.ran("git push") == []

    def test_a_missing_gh_is_exit_127(self):
        self.sim.missing = True
        assert self.deliver(StackItem(branch="task/a")) == 127


class RemoteOnly(StackCase):
    def test_a_branch_only_origin_has_is_fetched_and_delivered(self):
        del self.git.local["task/b"]
        self.sim.remote["task/b"] = OID["task/b"]
        assert self.deliver(StackItem(branch="task/b")) == 0
        assert self.sim.ran("git ls-remote origin refs/heads/task/b")[:1] == ["git ls-remote origin refs/heads/task/b"]
        assert self.sim.ran("git fetch origin")
        assert [b for b, _, _ in self.recorded] == ["b"]

    def test_a_name_that_exists_nowhere_is_refused_naming_the_commands(self):
        assert self.deliver(StackItem(branch="task/zzz")) == 1
        why = self.kinds("warn")[0]["text"]
        assert "git ls-remote origin refs/heads/task/zzz" in why
        assert "git rev-parse --verify refs/heads/task/zzz" in why
        assert self.sim.ran("gh pr create") == []

    def test_a_failing_fetch_names_the_command(self):
        del self.git.local["task/b"]
        self.sim.remote["task/b"] = OID["task/b"]
        self.sim.fail["git fetch"] = 4
        assert self.deliver(StackItem(branch="task/b")) == 1
        assert "git fetch origin" in self.kinds("warn")[0]["text"]


class StoredGate(StackCase):
    def test_delivery_compares_planned_skips_to_the_base_policy_producer(self):
        stores = real_stores(self.cfg)
        tree, base = TreeSha("tree-" + OID["task/a"][:6]), BaseSha("origin/main")
        keys = InputKeys(self.git, str(self.repo), tree)
        keys.files = {}
        memo = RunMemo(stores, check_files.repo_key(self.git, str(self.repo)), keys, base, {"TL_SLOT": "check"})
        check = Check(id=CheckId("lint"), cmd="true", when=["src/**"])
        cmd = ["repo-plan", "steps", "--json"]
        skip = CheckResult.skipped(check, "no change under src/**").replace(planned=True)
        memo.remember(memo.planned_key(check, plan_digest(cmd)), skip, 1, "")
        profile = {"engine": {"plan_cmd": ["old-plan"], "checks": [
            {"id": "lint", "argv": ["true"], "run": "gate", "when": ["src/**"]}]}}
        (self.repo / ".task-loop.json").write_text(json.dumps(profile))
        self.git.profiles[OID["task/a"]] = json.dumps(profile)
        self.git.profiles["origin/main"] = json.dumps(profile)
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert self.sim.ran("git push") == []
        assert self.sim.ran("gh pr merge") == []
        profile["engine"]["plan_cmd"] = cmd
        self.git.profiles[OID["task/a"]] = json.dumps(profile)
        self.git.profiles["origin/main"] = json.dumps(profile)
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert len(self.sim.ran("tl check")) == 1  # the first delivery's fresh gate run; the second found the receipt

    def test_a_stored_planned_skip_satisfies_stackgate_only_for_its_tree_and_base(self):
        stores = fake_stores()
        tree, base = TreeSha("tree-a"), BaseSha("base-a")
        keys = InputKeys(self.git, str(self.repo), tree)
        keys.files = {}
        memo = RunMemo(stores, check_files.repo_key(self.git, str(self.repo)), keys, base, {"TL_SLOT": "check"})
        check = Check(id=CheckId("coverage"), cmd="coverage", when=["src/**"])
        skip = CheckResult.skipped(check, "no change under src/**").replace(planned=True)
        memo.remember(memo.planned_key(check), skip, 1, "")
        log = RunLog(stores.run_log("gate-test"), run_id="gate-test", host="h")
        gate = StackGate(Cmds(self.sim, log, str(self.repo)), self.git, stores, str(self.repo), "origin/main", ["tl"])
        spec = {"id": "coverage", "argv": ["coverage"], "run": "gate", "when": ["src/**"]}
        engine = load({"engine": {"checks": [spec]}}).engine
        assert gate.red(engine, tree, base) == []
        assert gate.red(engine, "other-tree", base) == [check.id]
        assert gate.red(engine, tree, "other-base") == [check.id]
        other = load({"engine": {"checks": [{**spec, "id": "never-ran"}]}}).engine
        assert gate.red(other, tree, base) == ["never-ran"]
        memo.remember(memo.planned_key(check), skip.replace(planned=False, why="static failed first"), 2, "")
        assert gate.red(engine, tree, base) == []  # invalid skip cannot overwrite a satisfied decision
        cmd = ["repo-plan", "steps", "--json"]
        memo.remember(memo.planned_key(check, plan_digest(cmd)), skip, 3, "")
        profile = self.repo / ".task-loop.json"
        profile.write_text(json.dumps({"engine": {"plan_cmd": ["stale-plan"]}}))
        for argv, red in ((cmd, []), (["repo-plan", "changed"], [check.id]), (cmd, [])):
            with self.subTest(argv=argv):
                self.git.profiles[OID["task/a"]] = json.dumps({"engine": {"plan_cmd": argv, "checks": [spec]}})
                engine = gate.profile(OID["task/a"])
                assert engine is not None
                assert gate.red(engine, tree, base) == red


class GateCase(StackCase):
    def setup_method(self):
        super().setup_method()
        profile = '{"engine": {"checks": [{"id": "lint", "argv": ["true"], "run": "gate"}]}}'
        self.git.profiles = dict.fromkeys([*OID.values(), "origin/main"], profile)
        self.green: set[str] = set()  # trees the store holds a pass for
        patch = mock.patch.object(StackGate, "red", lambda gate, engine, tree, base, wt="":
                                  [] if tree in self.green else [CheckId("lint")])
        patch.start()
        self.addCleanup(patch.stop)


class Gated(GateCase):
    def test_a_green_tree_is_delivered_without_a_run(self):
        self.green.add("tree-" + OID["task/a"][:6])
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.sim.ran("tl check") == []

    def green_on_check(self):
        real_run = self.sim.run

        def run(argv, **kw):
            if argv[:2] == ["tl", "check"]:
                self.green.add("tree-" + OID["task/a"][:6])
            return real_run(argv, **kw)

        self.sim.run = run

    def test_a_red_tree_with_no_worktree_is_gated_in_a_fresh_one_then_delivered(self):
        self.green_on_check()
        assert self.deliver(StackItem(branch="task/a")) == 0
        (path,) = [c[1] for c in self.git.calls if c[0] == "add_worktree"]
        assert self.git.heads[path] == OID["task/a"]
        assert self.sim.ran("tl check --repo " + path) == ["tl check --repo " + path]
        assert self.git.ran("remove_worktree_force", path)

    def test_a_carried_pass_is_delivered_without_running_the_check(self):
        def carried(carry, engine, step, oid, tree, base, wt):
            self.green.add(tree)
            return True

        with mock.patch.object(Carry, "carried", carried):
            assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.sim.ran("tl check") == []

    def test_a_pass_that_is_not_carried_runs_the_check(self):
        self.green_on_check()
        with mock.patch.object(Carry, "carried", lambda *a: False):
            assert self.deliver(StackItem(branch="task/a")) == 0
        assert len(self.sim.ran("tl check")) == 1

    def test_a_listed_worktree_whose_directory_is_gone_is_a_miss_not_a_crash(self):
        self.git.worktrees["task/a"] = "/wt/gone"
        self.git.gone.add("/wt/gone")
        self.green_on_check()
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.sim.ran("tl check --repo /wt/gone") == []
        assert any(c[0] == "add_worktree" for c in self.git.calls)

    def test_a_fresh_worktree_is_removed_when_the_gate_stays_red(self):
        self.sim.fail["tl check"] = 6
        assert self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")) == 6
        assert self.sim.ran("git push") == []
        assert self.git.ran("remove_worktree_force")

    def test_a_red_tree_in_a_clean_worktree_is_gated_then_delivered(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        real_run = self.sim.run

        def run(argv, **kw):
            if argv[:2] == ["tl", "check"]:
                self.green.add("tree-" + OID["task/a"][:6])
            return real_run(argv, **kw)

        self.sim.run = run
        assert self.deliver(StackItem(branch="task/a")) == 0
        assert self.sim.ran("tl check --repo /wt/a") == ["tl check --repo /wt/a"]

    def test_a_gate_that_stays_red_stops_with_its_exit_code_and_later_items_untouched(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        self.sim.fail["tl check"] = 6
        assert self.deliver(StackItem(branch="task/a"), StackItem(branch="task/b")) == 6
        assert self.sim.ran("git push") == []
        assert "tl check --repo /wt/a" in self.kinds("warn")[0]["text"]

    def test_a_dirty_worktree_is_not_gated_a_fresh_one_is(self):
        self.git.worktrees["task/a"] = "/wt/a"
        self.git.heads["/wt/a"] = OID["task/a"]
        self.git.dirty_at.add("/wt/a")
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert self.sim.ran("tl check --repo /wt/a") == []  # the dirty checkout is the caller's; the gate judges the oid in a fresh one
        assert len(self.sim.ran("tl check")) == 1

    def test_a_repo_without_a_gate_step_passes(self):
        self.git.profiles[OID["task/a"]] = '{"engine": {"checks": [{"id": "x", "argv": ["true"], "run": "stage"}]}}'
        self.git.profiles["origin/main"] = self.git.profiles[OID["task/a"]]
        assert self.deliver(StackItem(branch="task/a")) == 0

    def test_a_stale_checkout_cannot_replace_the_base_policy(self):
        (self.repo / ".task-loop.json").write_text(
            '{"engine": {"checks": [{"id": "coverage", "argv": ["true"], "run": "gate"}]}}')
        with mock.patch.object(StackGate, "red", return_value=[]) as green:
            assert self.deliver(StackItem(branch="task/a")) == 0
        assert [[check.id for check in call.args[0].gate_checks] for call in green.call_args_list] == [["lint"]]
        assert self.git.ran("show", "origin/main", ".task-loop.json")

    def test_a_checkout_without_checks_cannot_remove_the_base_gate(self):
        (self.repo / ".task-loop.json").write_text('{"engine": {"checks": []}}')
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert "not green for lint" in self.kinds("warn")[0]["text"]
        assert self.sim.ran("git push") == []
        assert self.sim.ran("gh pr merge") == []

    def test_a_profile_removed_by_the_judged_commit_is_refused(self):
        (self.repo / ".task-loop.json").write_text(self.git.profiles.pop(OID["task/a"]))
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert "profile_changed: task/a" in self.kinds("warn")[0]["text"]
        assert self.sim.ran("tl check") == []

    def test_an_invalid_judged_profile_stops_before_push_or_merge(self):
        self.git.profiles[OID["task/a"]] = "{"
        assert self.deliver(StackItem(branch="task/a")) == 1
        assert "profile_changed: task/a" in self.kinds("warn")[0]["text"]
        assert self.sim.ran("git push") == []
        assert self.sim.ran("gh pr merge") == []

    def test_a_git_profile_read_failure_cannot_bypass_the_gate(self):
        with mock.patch.object(self.git, "show", side_effect=SlotGitError("cannot read object")):
            assert self.deliver(StackItem(branch="task/a")) == 1
        assert "cannot read object" in self.kinds("warn")[0]["text"]
        assert self.sim.ran("git push") == []
        assert self.sim.ran("gh pr merge") == []


class Verb(StackCase):
    def own_worktree(self):
        """Remove the actual --repo directory and reject any later use of a missing cwd."""
        main = Path(self.tmp.name) / "main"
        main.mkdir()
        self.git.worktrees["task/a"] = str(self.repo)
        self.git.common_dir = lambda d: str(main / ".git")
        self.git.checkouts = lambda d: [Checkout(path=str(main), branch="main", main=True),
                                       *(Checkout(path=p, branch=b, main=False) for b, p in self.git.worktrees.items())]
        remove = self.git.remove_worktree_why

        def removing(repo, path):
            assert Path(repo).is_dir()
            Path(path).rmdir()
            return remove(repo, path)

        self.git.remove_worktree_why = removing

        def guarded(fn):
            def call(cwd, *args, **kw):
                assert Path(cwd).is_dir(), f"{fn.__name__} used removed cwd {cwd}"
                return fn(cwd, *args, **kw)
            return call

        for name in ("rev_parse", "common_dir", "checkouts", "fetch", "push", "ls_remote", "log", "ls_tree", "show",
                     "delete_branch_at", "remote_url", "config_get", "is_ancestor"):
            patch = mock.patch.object(self.git, name, side_effect=guarded(getattr(self.git, name)))
            patch.start()
            self.addCleanup(patch.stop)
        run = self.sim.run

        def running(argv, **kw):
            if kw.get("cwd"):
                assert Path(kw["cwd"]).is_dir()
            return run(argv, **kw)

        self.sim.run = running
        store = self.bd("a", "b")

        def sync():
            return self.synced if self.repo.is_dir() else DoltPush(127, "cwd removed")

        store.dolt_push = sync  # type: ignore[method-assign]
        return store

    def test_repo_is_the_landed_worktree_and_sync_succeeds(self):
        store = self.own_worktree()
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        assert self.verb(["task/a"], [], who, store) == 0
        assert not self.repo.exists()
        assert self.git.deleted == ["task/a"]

    def test_repo_is_the_landed_worktree_until_sync_and_later_items_finish(self):
        store = self.own_worktree()
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        self.sim.pr(5, "old", "o" * 40)
        args = Namespace(items=["task/a", "task/b"], repo=str(self.repo), base="main", method="squash", bead=[],
                         supersede=["task/a=5"], wait_min=None, profile_change=None)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_land_stack(args, who, self.git, self.sim, store, ["tl"])
        assert rc == 0
        assert not self.repo.exists()
        assert self.git.deleted == ["task/a", "task/b"]
        assert self.sim.prs[5]["state"] == "CLOSED"
        (bundle,) = [b for b in RunLocator(self.cfg).runs() if b.manifest.mode == MODE]
        assert bundle.manifest.state.value == "done"
        rows = records(bundle.log)
        done = [row for row in rows if row["kind"] == "land_cleanup" and row["local_outcome"] == "gone"]
        assert [(row["branch"], row["bead"]) for row in done] == [("task/a", "a"), ("task/b", "b")]
        sync = next(i for i, row in enumerate(rows) if row.get("text") == "bd sync --no-adopt")
        removed = next(i for i, row in enumerate(rows) if row.get("text", "").startswith("removed worktree"))
        assert sync < removed

    def test_repo_worktree_cleanup_after_partial_land_preserves_the_original_failure(self):
        store = self.own_worktree()
        self.sim.fail["gh pr merge 2"] = 9
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        assert self.verb(["task/a", "task/b"], [], who, store) == 9
        assert not self.repo.exists()
        assert self.git.deleted == ["task/a"]
        assert "failed (exit 9)" in self.output

    def test_repo_worktree_cleanup_still_runs_after_sync_failure(self):
        store = self.own_worktree()
        self.synced = DoltPush(2, "conflict")
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        assert self.verb(["task/a"], [], who, store) == 2
        assert not self.repo.exists()
        assert self.git.deleted == ["task/a"]
        assert "bd sync failed (exit 2): conflict" in self.output

    def test_owner_profile_flag_lands_and_writes_one_shared_audit_row(self):
        text = 'Denis: "I approve the profile" 2026-11-02T12:00Z'
        patch = 'diff --git a/.task-loop.json b/.task-loop.json\n-old\n+new\n'
        self.git.profiles["origin/main"] = "{}"
        self.git.profiles[OID["task/a"]] = '{"engine": {"checks": []}}'
        args = Namespace(items=["task/a"], repo=str(self.repo), base="main", method="squash", bead=[], supersede=[],
                         wait_min=None, profile_change=text)
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        with (contextlib.redirect_stdout(io.StringIO()), mock.patch.object(self.git, "profile_diff", return_value=patch)):
            rc = cmd_land_stack(args, who, self.git, self.sim, self.bd("a"), ["tl"], env=Env())
        assert rc == 0
        rows = [item.rec for item in real_stores(self.cfg).profile_changes.read_from().items]
        assert len(rows) == 1
        assert (rows[0].owner_text, rows[0].tip, rows[0].diff_sha) == (text, OID["task/a"], hashlib.sha256(patch.encode()).hexdigest())
        assert self.sim.ran("git push")

    def test_an_unknown_explicit_bead_stops_the_whole_stack_before_push_or_merge(self):
        who = Identity(actor="tl-me", home=self.tmp.name, session="s")
        for items, beads in ((["task/a", "task/b"], ["task/b=missing-bead"]), (["293"], ["293=missing-bead"])):
            with self.subTest(items=items):
                assert self.verb(items, beads, who) != 0
                assert "unknown bead missing-bead" in self.output
                assert self.sim.ran("git push") == []
                assert self.sim.ran("gh pr merge") == []
        for bundle in RunLocator(who.config).runs():
            assert bundle.manifest.state.value == "failed"
            assert "missing-bead" in bundle.manifest.reason
            close = [r for r in records(bundle.log) if r["kind"] == "close"][-1]
            assert close["outcome"] == "failed"
            assert "missing-bead" in close["why"]

    def test_the_verb_makes_a_run_the_board_finds_through_its_manifest(self):
        a = Namespace(items=["task/a", "task/b"], repo=str(self.repo), base="main", method="squash", bead=["task/b=tl-b"], supersede=[],
                      wait_min=None, profile_change=None)
        store = self.bd("a", "tl-b")
        who = Identity(actor="tl-me", home=self.tmp.name, session="sess-1")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_land_stack(a, who, self.git, self.sim, store, ["tl"])
        assert rc == 0
        (bundle,) = [b for b in RunLocator(self.cfg).runs() if b.manifest.mode == MODE]
        assert bundle.manifest.ended is not None
        rows = records(bundle.log)
        assert rows[0]["mode"] == MODE
        assert all(closeguard.has_land(who, BeadId(b)) for b in ("a", "tl-b"))
        m = bundle.manifest
        assert (m.mode, m.owner, m.session, m.bead, m.beads) == (MODE, "tl-me", "sess-1", "a", ("tl-b",))
        assert m.state.value == "done"
        assert any(r["kind"] == "cmd_start" and r["text"].startswith("git push") for r in rows)
        assert any(r["kind"] == "cmd_start" and r["text"].startswith("gh pr merge") for r in rows)

    def bd(self, *beads):
        store = FakeBeads(actor="tl-me")
        store.dolt_push = lambda: DoltPush(0, "")  # type: ignore[method-assign]
        for b in beads:
            store.beads[BeadId(b)] = Bead(id=BeadId(b), title="t", status="open", issue_type="task")
        return store

    def verb(self, items, bead, who, store=None):
        a = Namespace(items=items, repo=str(self.repo), base="main", method="squash", bead=bead, supersede=[], wait_min=None,
                      profile_change=None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_land_stack(a, who, self.git, self.sim, store or self.bd("lifesim-fvit"), ["tl"])
        self.output = out.getvalue()
        return rc

    def test_a_pr_number_with_a_bead_shows_its_landing_in_tl_trace_and_the_manifest(self):
        root = Path(self.tmp.name) / "xdg"
        who = Identity(actor="tl-me", home=str(root / "task-loop"), session="sess-1")
        self.sim.pr(293, "task/a", OID["task/a"])
        assert self.verb(["293"], ["293=lifesim-fvit"], who) == 0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            trace(BeadId("lifesim-fvit"), 0, False, Env(vars={"XDG_CONFIG_HOME": str(root)}))
        assert "lifesim-fvit  landed" in out.getvalue()
        assert "landed " + "merge293"[:12] in out.getvalue()
        (bundle,) = [b for b in RunLocator(who.config).runs() if b.manifest.mode == MODE]
        assert bundle.manifest.bead == "lifesim-fvit"

    def test_after_a_pr_number_land_the_bead_closes_with_no_extra_step(self):
        who = Identity(actor="tl-me", home=str(Path(self.tmp.name) / "xdg2"), session="sess-1")
        store = self.bd("lifesim-fvit")
        self.sim.pr(294, "task/a", OID["task/a"])
        RunLocator(who.config).create(str(self.repo), "lifesim-fvit", 1.0)  # the bead has an engine run, and no land yet
        guard = closeguard.guard_for(who, store, self.git, str(self.repo))
        assert "no land on record" in guard(BeadId("lifesim-fvit"), "done")
        assert self.verb(["294"], ["294=lifesim-fvit"], who, store) == 0
        assert guard(BeadId("lifesim-fvit"), "done") == ""

    def test_a_bead_for_an_item_that_is_not_given_is_refused_naming_both(self):
        who = Identity(actor="tl-me", home=self.tmp.name, session="s")
        with pytest.raises(SystemExit) as e:
            self.verb(["293"], ["task/x=lifesim-okrs"], who)
        assert "task/x" in str(e.value)
        assert "293" in str(e.value)
        assert self.sim.calls == []
