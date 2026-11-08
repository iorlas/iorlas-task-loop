"""Engine tests: the land, the push, the rebase and the conflict fix."""
import re
import signal as sig
import sys
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import gitq, homes
from support.engine_case import _cells, no_repo, stop
from support.engine_land import EngineLandMixin, EngineTest, real_lander
from support.gitsim import verbs

from tltestkit.checks import typed
from tltestkit.plans import CLEAN, FALSE, HAS_F, PLAN, WRITE, finding, review
from tltestkit.shellkit import ENGINE_BASH, POSIX_CHECK, sh

# isort: split
import contextlib
import fcntl
import json
import os
import time
from pathlib import Path
from unittest import mock

from support.interrupts import Interrupter, Recovery, RecoveryRig

from taskloop.adapters import (
    ident,
)
from taskloop.app.run import engine
from tlgate.domain import lint
from tlkernel.config import EngineConfig
from tltestkit import fake_route, procsim
from tltestkit.cfgs import cfg_with
from tltestkit.logs import records
from tltestkit.narrow import must
from tlwork.plan.matchers import gate_only_criteria
from tlwork.plan.planner import Planner


class EngineLand1Test(EngineLandMixin, EngineTest):
    def test_happy_path_lands_and_closes(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert self.closed and self.closed[0].startswith("merged ")
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"
        remote = gitq.git("rev-parse", "origin/main", cwd=str(self.wt))
        # the one landed record, in the bead's metadata: the sha pushed, which origin/main now is
        meta = [str(a) for c in self.bd_calls if c[:1] == ("update",) for a in c if "landed_sha" in str(a) or "landed_base" in str(a)]
        assert any(remote in a for a in meta) and any("origin/main" in a for a in meta), meta
        assert any(c[:2] == ("comments", "add") and "Reflect (engine)" in c[3] for c in self.bd_calls)
        # the facets of this one run, each of which used to be a run of its own
        assert s.requests[2].reviewer_other_family
        assert s.results[2]["family"] != s.results[1]["family"]
        rv = s.prompts[2]
        assert "git diff HEAD" not in rv
        assert "<diff>\ndiff --git a/f.txt b/f.txt" in rv  # the stage's diff, inline (tl-bxk.10.18)
        for fact in ("exit 0", "wrote f", "evidence", "add f"):
            assert fact in rv
        runs = [json.loads(ln) for ln in (homes.config_dir() / "traces.jsonl").read_text().splitlines()]
        assert len(runs) == 1
        r = runs[0]
        assert (r["bead"], r["outcome"], r["coordinator_session"]) == ("t-1", "landed", "sess1234-x")
        assert [x["role"] for x in r["sessions"]] == ["planner", "worker", "reviewer"]
        assert r["sessions"][1]["ref"] == "ref-write"
        assert any(c[:2] == ("comments", "add") and "trace=" + r["run"] in c[3] for c in self.bd_calls)
        assert r["sessions"][1]["tokens"] == {"in": 1000, "cached": 800, "out": 50}
        assert (r["stats"]["tokens_in"], r["stats"]["tokens_cached"], r["stats"]["tokens_out"]) == (3000, 2400, 150)
        assert [(w["write"], w["resumed"], w["input_tokens"]) for w in r["write_rounds"]] == [(1, "no", 1000)]
        res = self.eng.result()  # the landed run's stats, trace and log
        assert res.outcome == "landed"
        assert (res.bead, res.run, res.log) == ("t-1", self.eng.run_id, str(self.eng.log_path))
        assert not res.asked
        assert gitq.git("symbolic-ref", "--short", "-q", "HEAD", cwd=self.eng.wt)  # a landed bead leaves the slot on a branch
        want = json.loads((ident.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
        assert ident.plugin_version() == want  # the log and trace record the plugin version
        assert f"task-loop {want}" in self.eng.log_path.read_text()
        assert r["version"] == want

    def test_a_fetch_that_loses_the_ref_lock_to_a_sibling_worktree_is_tried_again(self):
        # race test (tl-bxk.11.1): worktrees share refs/remotes/origin/main; a fetch at the same time as another
        # process's (a loop's queue, a slot reset, a release) fails "incorrect old value provided" though the ref is
        # then right. The reset's fetch failed the bead; the land's failed it as "fetch or rebase ... failed".
        assert self.sim
        self.sim.fail(("fetch",), "error: fetching ref refs/remotes/origin/main failed: incorrect old value provided",
                      when=lambda n: n % 2 == 1)  # every first try of a fetch loses
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert sum(verbs(c)[:1] == ["fetch"] for c in self.sim.calls) >= 4  # reset and land: each lost once, then won
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"

    def test_a_hung_gate_is_cut_at_gate_timeout_min_and_goes_red(self):
        gate = procsim.fake("hung-gate", procsim.hangs())
        t = time.time()
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=gate,
                                gate_timeout_min=0.02, max_fix_rounds=0)
        assert time.time() - t < 20
        assert rc != 0
        assert "timed out after 0.02 min" in self.eng.log_path.read_text()

    @POSIX_CHECK
    def test_a_gate_killed_by_a_signal_starts_no_fix_round_and_leaves_the_bead_open(self):
        # tl-y35: `gate: exit -15` (the parent stopped it) is the machine's outcome, not the code's
        rc, s = self.run_engine(
            {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
            gate=procsim.fake("killed-gate", procsim.exits(-15)),
            max_fix_rounds=2,
        )
        assert rc != 0
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]  # no fix round: no second worker call
        assert (self.eng.fixes, self.blocked, self.closed) == (0, [], [])
        assert ("update", "t-1", "--status", "open", "--assignee", "") in self.bd_calls
        log = self.eng.log_path.read_text()
        assert [g["exit"] for g in records(self.eng, "gate_end")] == [-15]
        assert "gate red" not in log

    def test_a_land_lock_wait_is_not_budget(self):
        # tl-y35: 2251 s on the fake clock waiting for the land lock move the budget by exactly that
        eng = self.checks_engine(budget_min=180)
        eng.budget.now = eng.clock.now  # the budget counts on the clock the wait is measured on, as in a run
        eng.budget.restore(0.0, 0.0)
        before = eng.budget.spent_min()

        @contextlib.contextmanager
        def held_by_another(path, holder, waiting=None, timeout=None, check=None):
            must(waiting)("tl-266")
            cast(Any, eng.clock).advance(2251)  # the test's fake clock
            yield path
        eng.os_lock = held_by_another
        with eng.waits.locked("land_lock", Path(self.tmp.name) / "land.lock"):
            pass
        assert eng.waited == 2251
        assert eng.budget.spent_min() == before  # the wait moved the clock and the budget minutes by nothing
        (start,), (end,) = records(eng, "wait_start"), records(eng, "wait_end")
        assert (
            (start["holder"], start["id"], end["id"], end["wait_seconds"], end["in_budget"])
            == ("tl-266", end["id"], start["id"], 2251, False)
        )

    def test_the_gate_runs_once_at_land(self):
        count = Path(self.tmp.name) / "gates"
        gate = procsim.fake("count-gate", procsim.appends(count))
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=gate)
        assert rc == 0
        assert count.read_text() == "1"

    def test_writer_is_told_the_repo_worker_rules_and_never_to_run_the_gate(self):
        self.put_repo_file("docs/agents/worker-rules.md", "RULES-MARK: unity runs on the host\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/worker-rules.md", gate="true")
        assert rc == 0
        w = next(p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker")
        assert w.count("RULES-MARK") == 1  # inlined once, by text
        assert "worker-rules.md" not in w  # no path to read (tl-7y6.6.1)
        assert "Read " not in w.split("<worker_rules>")[0].rsplit("Your stage", 1)[-1]
        assert '(`true`) or the issue tracker (bd)' in w

    def test_wip_from_an_earlier_run_lands_as_one_titled_commit(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from run 1\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        log = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        assert log == ["Add f (t-1)", "init"]
        assert gitq.git("show", "origin/main:g.txt", cwd=str(self.wt)) == "from run 1"

    UNITY: ClassVar[Any] = {"cmd": "echo unity-check", "why": "it fails on uncommitted client/ changes"}

    def test_a_check_running_a_gate_only_command_is_sent_back_to_the_planner_once(self):
        # lifesim-fld.27.9: a stage check ran `just unity-check`, red by design on the uncommitted tree: stuck, 68 min
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, "env CI=1 echo unity-check"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, gate_only=[self.UNITY])
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "echo unity-check runs only in the gate at land: it fails on uncommitted client/ changes" in s.prompts[1]
        assert "echo unity-check" in s.prompts[0]  # the planner is told up front too

    def test_the_gate_command_is_always_gate_only(self):
        bad = dict(PLAN, cases=[{"criterion": "the repo is green", "check": "just  check"}])
        rc, s = self.run_engine({"plan": [bad, bad], "write": [WRITE], "review": [CLEAN]},
                                gate=procsim.fake("just check", procsim.exits(0)))
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "just check runs only in the gate at land" in s.prompts[1]
        assert self.blocked == []
        plan = self.eng.plan_data
        assert plan is not None
        assert "left to the gate" in Planner.summary(plan)

    def test_acceptance_that_is_only_the_gate_is_sent_back_naming_the_rule(self):
        # tl-7y6.7.15: the engine runs the gate at land; "just check green" as acceptance proves nothing the land does not
        gate = "true"
        crit = f"`{gate}` passes (green)"
        only = dict(PLAN, cases=[{"criterion": crit, "check": "", "class": "taste"}])
        good = dict(PLAN, cases=[{"criterion": "f.txt exists", "check": HAS_F}])
        rc, s = self.run_engine({"plan": [only, good], "write": [WRITE], "review": [CLEAN]}, gate=gate)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "planner", "worker", "reviewer"]
        assert "plan-lint rule gate-only-acceptance" in s.prompts[1]
        assert "- " + crit in s.prompts[1]

    def test_acceptance_still_only_the_gate_after_one_rewrite_blocks(self):
        only = dict(PLAN, cases=[{"criterion": "Done when: just check is green", "check": HAS_F}])
        _rc, s = self.run_engine({"plan": [only, only]}, gate="just check")
        assert [c[0] for c in s.calls] == ["planner", "planner"]
        assert self.blocked == []
        assert "gate-only-acceptance" in self.said()

    def test_gate_only_criteria_match_the_gate_alone_not_a_case_that_names_it_with_more(self):
        cfg = cfg_with(gate="just check", gate_only=["just unity-check"])
        def cases(*cs):
            return {"cases": [{"criterion": c, "check": ""} for c in cs]}

        bad = [
            "just check",
            "`just  check` passes",
            "The gate (just check) is green.",
            "just unity-check exits 0",
            "Done when: just check green",
        ]
        ok = ["f.txt exists", "just check-fmt passes", "the greeting shows after just check ran the migration", "just fmt is clean"]
        assert gate_only_criteria(cases(*bad, *ok), cfg) == bad
        assert gate_only_criteria(cases("just check passes"), cfg_with()) == []

    def test_gate_only_checks_match_a_command_not_a_longer_name_or_an_argument(self):
        cfg = cfg_with(gate="just check", gate_only=["just unity-check", self.UNITY])
        bad = ["just check", "env CI=1 just unity-check --fast", "nice just check"]
        ok = [HAS_F, "just check-fmt", "just unity-checks", "grep 'just check' AGENTS.md", "just fmt"]
        got = lint.gate_only_checks(typed(dict(PLAN, risks=[{"what": "x", "check": c} for c in bad + ok])), cfg)
        assert [c for c, _ in got] == bad
        assert lint.gate_only_checks(typed(dict(PLAN, risks=[{"what": "x", "check": "just check"}])),
                                                 cfg_with()) == []

    def test_the_planner_gets_the_repo_rules_and_is_told_the_engine_owns_the_gate(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/codex.md", gate=procsim.fake("just check", procsim.exits(0)), max_fix_rounds=0)
        assert "codex.md" not in s.prompts[0]
        assert "never put `just check` in a stage" in s.prompts[0]

    def test_two_accepted_requirements_in_conflict_are_still_a_decision_ask(self):
        self.asks_the_owner("R3 says keep saves forever, R7 says drop them after a week: which wins?")

    @no_repo
    def test_check_timeout_defaults_to_60_min_and_the_gate_to_90(self):
        assert (EngineConfig().check_wall_min, EngineConfig().gate_timeout_min) == (60, 90)




    def test_a_stop_while_the_land_is_recorded_still_closes_it_landed(self):
        def stop_at_the_land_record(*argv):
            if argv[:2] == ("provenance", "record") and "land" in argv:
                os.kill(os.getpid(), sig.SIGTERM)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with self.stoppable(), self.store.stub(bd_fn=stop_at_the_land_record):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert (rc, self.eng.result().outcome) == (0, "landed")
        assert self.blocked == []


    def test_a_rerun_after_a_red_land_gate_lands_the_reviewed_work_once(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=FALSE, max_fix_rounds=0)
        assert rc == 2
        assert "gate red" in self.blocked[0]
        first = gitq.git("rev-parse", "task/t-1", cwd=str(self.wt))
        assert gitq.git("show", "task/t-1:f.txt", cwd=str(self.wt)) == "d2"
        idle = dict(WRITE, summary="re-proved, no change")
        with mock.patch.object(fake_route.Script, "reply", self.no_write(fake_route.Script.reply)), \
                self.store.stub(comments=[{"author": "denis", "text": "Rerun it."}]):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [idle], "review": [CLEAN]})
        assert rc == 0
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"
        assert gitq.git("rev-list", "--count", "origin/main", f"^{first}~1", cwd=str(self.wt)) == "1"
        subjects = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        assert sum("(t-1)" in x for x in subjects) == 1
        assert not any(x.startswith("wip") for x in subjects)

    @staticmethod
    def no_write(real):
        def call(this, role, prompt, schema, cwd, *a, **kw):
            before = Path(cwd, "f.txt").read_text() if Path(cwd, "f.txt").exists() else None
            r = real(this, role, prompt, schema, cwd, *a, **kw)
            if role == "worker" and before is not None:
                Path(cwd, "f.txt").write_text(before)  # the rerun's writer changes nothing
            return r
        return call

    def test_reviewed_work_stopped_in_the_gate_goes_straight_to_land(self):
        with self.stoppable():
            gate = procsim.fake("kill -TERM $PPID; sleep 5", procsim.exits(1, "kill: illegal pid"))
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=gate)
        assert rc == 2
        assert self.checkpoint()["step"] == "land"
        rc, s = self.run_engine({})
        assert rc == 0
        assert s.calls == []
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"

    def test_a_red_gate_replans_with_its_output_and_keeps_the_accepted_stages(self):
        red = procsim.fake("red-gate", procsim.exits(1, "RS0016 ContentPack ctor"))
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=red)
        assert rc == 2  # two fix rounds could not make it green: the next run re-plans with the gate's output
        assert self.checkpoint()["step"] == "gate-red"
        fix = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="reconcile the API file")])
        with self.store.stub(comments=[{"author": "denis", "text": "Main moved; reconcile it."}]):
            rc, s = self.run_engine({"plan": [fix], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer"]
        assert "already accepted" in s.prompts[0]
        assert "RS0016 ContentPack ctor" in (self.eng.run_dir / "replan.md").read_text()

    @ENGINE_BASH
    def test_a_fault_in_a_conflict_fix_round_resumes_at_land(self):
        # lifesim-6dq0: the fix round's checkpoint was saved mid-rebase (detached HEAD), so the rerun re-planned
        other = Path(self.tmp.name, "other")
        real = fake_route.Script.reply

        def main_moves(this, role, *a, **kw):
            if role == "reviewer" and not other.exists():
                sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(other), cwd=self.tmp.name)
                (other / "f.txt").write_text("theirs\n")
                sh("git", "add", "-A", cwd=other)
                sh("git", "commit", "-qm", "theirs", cwd=other)
                sh("git", "push", "-q", "origin", "HEAD:main", cwd=other)
            return real(this, role, *a, **kw)
        denied = stop(
            "secrets",
            "w1",
            family="openai",
            denied=[{"kind": "policy", "tool": "Bash", "path": "", "input": {"command": "rg -n --glob '!**/.env*' '^<<<<<<<' ."}}],
        )
        with mock.patch.object(fake_route.Script, "reply", main_moves):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, denied], "review": [CLEAN]})
        assert rc == 2
        assert self.ask() is None  # tl-7y6.2.2: the refusal is a machine fault; the checkpoint is what resumes the run
        ck = self.checkpoint()
        assert (ck["step"], ck["branch"]) == ("land", gitq.git("symbolic-ref", "--short", "HEAD", cwd=str(self.wt)))
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["worker", "reviewer"]  # the fix round again, no plan
        assert "conflict" in s.prompts[0]

    def test_a_red_gate_goes_to_a_fix_round_and_lands(self):
        def saw(cwd, env):
            t = procsim.f_txt(cwd)
            return (1 if t == "d2" else 0), f"gate saw {t}"
        gate = procsim.fake("gate-saw", saw)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer", "worker", "reviewer"]
        fix = s.prompts[3]
        assert "gate saw d2" in fix
        assert "fix" in s.prompts[4].lower()
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d4"
        subjects = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        assert sum("(t-1)" in x for x in subjects) == 1

    def test_a_gate_fix_brief_has_the_gate_error_lines_its_log_and_the_engine_reruns_the_gate(self):
        def errors(cwd, env):
            red = procsim.f_txt(cwd) == "d2"
            return (1 if red else 0), "".join(f"error E{i:03d}: gate no\n" for i in range(18) if red)
        gate = procsim.fake("gate-errors", errors)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        assert rc == 0, self.blocked
        fix = s.prompts[3]
        for i in range(18):
            assert f"error E{int(i):03d}: gate no" in fix
        assert re.search(r"log: \S+gate\.r\d\.log", fix)
        assert "the engine re-runs them; fix from the output above" in fix

    @ENGINE_BASH
    def test_a_rebase_conflict_goes_to_a_fix_round_not_blocked(self):
        other = Path(self.tmp.name, "other")
        real = fake_route.Script.reply

        def main_moves(this, role, *a, **kw):
            if role == "reviewer" and not other.exists():  # another task lands f.txt while this one is reviewed
                sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(other), cwd=self.tmp.name)
                (other / "f.txt").write_text("theirs\n")
                sh("git", "add", "-A", cwd=other)
                sh("git", "commit", "-qm", "theirs", cwd=other)
                sh("git", "push", "-q", "origin", "HEAD:main", cwd=other)
            return real(this, role, *a, **kw)
        with mock.patch.object(fake_route.Script, "reply", main_moves):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        assert "conflict" in s.prompts[3]
        log = gitq.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        assert log[:2] == ["Add f (t-1)", "theirs"]
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d4"

    def conflict_run(self, answers, **cfg):
        """A run where another task lands f.txt while this one is reviewed: the land hits a planted conflict."""
        other = Path(self.tmp.name, "other")
        real = fake_route.Script.reply

        def main_moves(this, role, *a, **kw):
            if role == "reviewer" and not other.exists():
                sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(other), cwd=self.tmp.name)
                (other / "f.txt").write_text("theirs\n")
                sh("git", "add", "-A", cwd=other)
                sh("git", "commit", "-qm", "theirs", cwd=other)
                sh("git", "push", "-q", "origin", "HEAD:main", cwd=other)
            return real(this, role, *a, **kw)
        with mock.patch.object(fake_route.Script, "reply", main_moves):
            return self.run_engine(answers, **cfg)

    def count_check(self, name):
        log = Path(self.tmp.name, name + ".count")
        return procsim.fake(f"count-{name}", procsim.appends(log, "x")), log

    def checks_records(self):
        recs = [json.loads(x) for x in self.eng.log_path.read_text().splitlines()]
        return [r for r in recs if r.get("kind") == "checks"]

    @ENGINE_BASH
    def test_a_conflict_fix_runs_the_marker_check_and_the_build_not_the_stage_or_other_repo_checks(self):
        build, build_log = self.count_check("build")
        unit, unit_log = self.count_check("unit")
        stage_check, stage_log = self.count_check("stage")
        plan = self.plan_with(HAS_F, stage_check)
        repo = [
            {"id": "build", "cmd": build, "group": "static", "cache": False},
            {"id": "unit", "cmd": unit, "group": "tests", "cache": False},
        ]
        rc, s = self.conflict_run({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, checks=repo)
        assert rc == 0, self.blocked
        assert "conflict" in s.prompts[3]
        rounds = self.checks_records()
        assert len(rounds) == 2  # the stage, then the conflict fix
        fix = {i["id"]: i for i in rounds[1]["run"]["results"]}
        assert fix[engine.Engine.MARKERS]["status"] == "passed"
        assert fix["build"]["status"] == "passed"
        for skipped in ("unit", HAS_F, stage_check):
            assert (fix[skipped]["status"], fix[skipped]["why"]) == ("skipped", "conflict_fix"), skipped
        assert (len(build_log.read_text()), len(unit_log.read_text()), len(stage_log.read_text())) == (2, 1, 1)
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d4"

    @ENGINE_BASH
    def test_a_conflict_fix_leaving_markers_is_not_accepted_the_marker_check_still_runs(self):
        marked = dict(WRITE)
        real = fake_route.Script.reply

        def write_markers(this, role, *a, **kw):
            r = real(this, role, *a, **kw)
            if role == "worker" and len(this.calls) == 4:  # the conflict fix's first write
                Path(this.cwds[-1], "f.txt").write_text("<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> t\n")
            return r
        with mock.patch.object(fake_route.Script, "reply", write_markers):
            rc, _s = self.conflict_run({"plan": [PLAN], "write": [WRITE, marked, WRITE], "review": [CLEAN, CLEAN, CLEAN]})
        recs = [{i["id"]: i["status"] for i in r["run"]["results"]} for r in self.checks_records()]
        assert recs[1]["diff-check"] == "failed"  # git's diff check judged it first; the marker check, a later group, did not run
        assert recs[1][engine.Engine.MARKERS] == "skipped"
        assert rc == 0, self.blocked

    @ENGINE_BASH
    def test_a_red_gate_after_a_conflict_fix_still_gets_a_fix_round_and_the_gate_ran_once_on_the_result(self):
        flag = Path(self.tmp.name, "gate-ran")
        def red_once(cwd, env):
            seen = flag.exists()
            procsim.appends(flag, "x")(cwd, env)
            return (0 if seen else 1), ""
        gate = procsim.fake("red-once-gate", red_once)
        rc, s = self.conflict_run({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=gate)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls].count("worker") == 3  # the stage, the conflict fix, the gate fix
        assert self.eng.fixes == 2
        assert len(flag.read_text()) == 2  # red once, then green: one gate run per land try

    @ENGINE_BASH
    def test_the_fix_cap_stays_two_after_a_conflict_fix(self):
        rc, s = self.conflict_run({"plan": [PLAN], "write": [WRITE] * 4, "review": [CLEAN] * 4}, gate=FALSE)
        assert rc == 2
        assert [c[0] for c in s.calls].count("worker") == 3  # the stage, then 2 fix rounds: the conflict fix and one gate fix
        assert "2 fix rounds" in self.blocked[0]

    def test_push_race_retry_keeps_one_land_lock_and_lands(self):
        rc, events, state = self.run_push_race()
        assert rc == 0, self.blocked
        assert events == ["enter", "fetch", "rebase", "gate", "push",
                                  "fetch", "rebase", "checks", "gate", "push", "exit"]
        assert state["pushes"] == 2
        assert self.eng.result().outcome == "landed"
        assert self.closed[0].startswith("merged ")
        assert gitq.git("show", "origin/main:a.txt", cwd=str(self.wt)) == "concurrent 1"
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"
        assert gitq.git("rev-parse", "HEAD", cwd=str(self.wt)) == gitq.git("rev-parse", "main", cwd=str(self.race_origin))

    def test_push_race_retries_use_input_cache(self):
        counts = {key: Path(self.tmp.name, key) for key in ("changed", "same", "whole", "uncached", "stage", "case", "conservative")}

        def bump(key):
            return procsim.fake(f"bump-{key}", procsim.appends(counts[key]))

        checks = [{"id": key, "cmd": bump(key), "group": "tests", "inputs": [path], "inputs_only": True}
                  for key, path in (("changed", "a.txt"), ("same", "f.txt"))]
        checks += [{"id": "whole", "cmd": bump("whole"), "group": "tests"},
                   {"id": "uncached", "cmd": bump("uncached"), "group": "tests", "cache": False},
                   {"id": "conservative", "cmd": bump("conservative"), "group": "tests", "inputs": ["f.txt"]}]
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[bump("stage")])],
                    cases=[{"criterion": "case", "check": bump("case"), "class": "test", "proved_by": "check"}])
        rc, events, state = self.run_push_race(checks=checks, plan=plan)
        assert rc == 0, self.blocked
        assert events.count("enter") == 1
        assert {key: path.read_text() for key, path in counts.items()} == {key: "1" if key == "same" else "11" for key in counts}
        cached = {c.id for c in state["results"][0] if c.cached}
        assert cached == {"same"}

    def push_race_failure_path_cell(self, failure, after):
        rc, events, state = self.run_push_race(failure=failure)
        assert rc == 2
        assert events.count("enter") == 1
        assert events.count("exit") == 1
        assert not self.eng.landed_sha
        assert (events[-2:] if after else events[-1:]) == (["exit", after] if after else ["exit"])
        assert state["pushes"] == (2 if failure in ("push", "network", "stop") else 1)

    def test_push_race_failure_fix_lands_after_the_lock_is_released(self):
        rc, events, _state = self.run_push_race(failure="checks_fixed")
        assert rc == 0, self.blocked
        assert events.count("enter") == 2
        assert events.count("exit") == 2
        assert events[events.index("fix:verify") - 1] == "exit"
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d4"
        assert self.eng.result().outcome == "landed"

    def push_race_exhausted_cell(self, failure):
        rc, events, state = self.run_push_race(failure=failure, resume_failed_fix=True,
                                              max_rounds=1, max_check_tries=1)
        assert state["fix_result"] == "replan"
        assert state["first_rc"] == 2
        assert rc == 2, self.blocked
        assert "validation fix did not pass" in state["first_blocked"]
        assert state["checkpoint"]["step"] == "land-verify-red"
        assert state["checkpoint"]["closed"]
        assert ("still red" if failure == "checks_exhausted" else "a high fix") in state["checkpoint"]["feedback"]
        assert self.eng.resumed
        assert state["resume_calls"] == (["planner", "worker"] +
                         (["reviewer"] if failure == "review_exhausted" else []))
        assert len(state["resume_checks"]) == 1
        assert any(c.status == "failed" for c in state["resume_checks"][0]) == (failure == "checks_exhausted")
        assert state["pushes"] == 1  # only the initial, rejected push
        assert state["gates"] == 1  # a green gate cannot accept the failed fix
        assert events.count("enter") == 1
        assert events.count("exit") == 1
        assert events[-2:] == ["exit", "fix:verify"]
        assert not self.eng.landed_sha
        assert self.eng.result().outcome != "landed"
        assert not self.closed
        assert self.lands == []
        assert gitq.git("show", "main:a.txt", cwd=str(self.race_origin)) == "concurrent 1"
        assert gitq.git("ls-tree", "--name-only", "main", "f.txt", cwd=str(self.race_origin)) == ""

    def push_race_interrupted_cell(self, interruption, role):
        gate = "true"
        with self.stoppable(), RecoveryRig().patched():
            cut, recovery, closed_before = Interrupter(self, interruption, role), Recovery(self), len(self.closed)
            with cut.patched():
                rc, events, race = self.run_push_race(failure="checks_fixed", max_rounds=1, max_check_tries=1)
            self.assert_stopped(cut.seen, role, (rc, events, race), closed_before)
            env = {"XDG_CONFIG_HOME": race["config_home"], "APPDATA": race["config_home"]}
            with mock.patch.dict(os.environ, env), recovery.patched():
                self.recover_red(cut.seen, role, recovery, closed_before, gate)
                self.recover_green(recovery, closed_before, gate)

    def assert_stopped(self, seen, role, ran, closed_before):
        rc, events, race = ran
        assert rc == 2, self.blocked
        assert (
            bool(seen.get("fix_initialized"))
            == (role in ("worker", "reviewer", "transition", "failed_checks"))
        )  # a flag: the stop waits for a safe point
        assert seen.get("interrupted")
        if role in ("worker", "reviewer", "transition", "failed_checks"):
            assert events[-2:] == ["exit", "fix:verify"]
        else:
            assert events[-1] == "exit"
            assert "fix:verify" not in events
        assert events.count("enter") == 1
        assert events.count("exit") == 1
        assert race["pushes"] == 1
        assert not self.eng.landed_sha
        assert len(self.closed) == closed_before
        assert self.lands == []

    def recover_red(self, seen, role, recovery, closed_before, gate):
        ck = self.checkpoint()
        assert ck["closed"]
        assert ck["step"] == "land-verify-red"
        if role not in ("worker", "reviewer"):
            assert "retry check" in ck["pending_land_validation"]
            seen["failure"] = ck["pending_land_validation"]
        assert ck["feedback"] == seen["failure"]
        assert ck["pending_land_validation"] == seen["failure"]
        red_plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])]) if role != "reviewer" else PLAN
        red_review = review(findings=[finding("high")]) if role == "reviewer" else CLEAN
        with self.store.stub(comments=[{"author": "denis", "text": "Recover validation."}]):
            rc, script = self.run_engine({"plan": [red_plan], "write": [WRITE], "review": [red_review]},
                                         gate=gate, max_rounds=1, max_check_tries=1, max_replans=1)
        assert rc == 2, self.blocked
        assert self.eng.resumed
        assert [c[0] for c in script.calls] == ["planner", "worker"] + (["reviewer"] if role == "reviewer" else [])
        assert len(recovery.checks_run) == 1
        assert any(c.exit for c in recovery.checks_run[0]) == (role != "reviewer")
        assert seen["failure"] in self.checkpoint()["pending_land_validation"]
        assert self.checkpoint()["step"] == "land-verify-red"
        assert not recovery.pushes
        assert not self.eng.landed_sha
        assert len(self.closed) == closed_before
        assert self.lands == []

    def recover_green(self, recovery, closed_before, gate):
        with self.store.stub(comments=[{"author": "denis", "text": "Recover with passing checks and review."}]):
            rc, script = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                         gate=gate, max_rounds=1, max_check_tries=1, max_replans=2)
        assert rc == 0, self.blocked
        assert [c[0] for c in script.calls] == ["planner", "worker", "reviewer"]
        assert len(recovery.checks_run) == 2
        assert all(c.exit == 0 for c in recovery.checks_run[-1])
        assert len(recovery.pushes) == 1
        assert not self.eng.pending_land_validation
        self.assertNoCheckpoint()
        assert self.eng.result().outcome == "landed"
        assert len(self.closed) == closed_before + 1
        assert len(self.lands) == 1


    def test_land_lock_is_one_per_repo_across_processes(self):
        if os.name == "nt":
            pytest.skip("POSIX flock")
        eng = self.checks_engine()

        def probe(path):  # flock is per open file: a second descriptor sees what a second process sees
            with open(path, "a") as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return "held"
                return "free"
        with real_lander(eng).lock() as path:
            held = probe(path)
        assert (held, probe(path)) == ("held", "free")


_cells(EngineLand1Test, "push_race_failure_path_releases_land_lock", "push_race_failure_path_cell",
       (("fetch", None), ("checks", "fix:verify"), ("gate", "fix:gate"), ("push", None), ("network", "wait"),
        ("stop", None), ("conflict", "fix:conflict")))


_cells(
    EngineLand1Test,
    "push_race_exhausted_validation_fix_cannot_land",
    "push_race_exhausted_cell",
    (("checks_exhausted",), ("review_exhausted",)),
)


_cells(EngineLand1Test, "push_race_interrupted_validation_fix_resume_requires_acceptance", "push_race_interrupted_cell",
       [("denial", "reviewer"), ("pause", "worker"),
        ("SIGTERM", "failed_checks"), ("SIGTERM", "checkpoint"), ("SIGTERM", "transition")])
