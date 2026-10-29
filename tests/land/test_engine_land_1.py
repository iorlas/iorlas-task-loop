"""Engine tests: the land, the push, the rebase and the conflict fix."""
import signal as sig
import sys
from pathlib import Path
from typing import Any, ClassVar, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import (
    CLEAN,
    ENGINE_BASH,
    FALSE,
    HAS_F,
    PLAN,
    POSIX_CHECK,
    PY,
    WRITE,
    EngineTest,
    _cells,
    finding,
    no_repo,
    pyc,
    review,
    sh,
    stop,
)

# isort: split
import contextlib
import json
import os
import shlex
import signal
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from support import fake_route
from support.builders import cfg_with
from support.interrupts import Interrupter, Recovery
from support.logs import records
from support.narrow import must

from taskloop.adapters import (
    gitrepo,
    ident,
)
from taskloop.app.run import engine
from taskloop.contracts.config import EngineConfig
from taskloop.domain import outcome as oc
from taskloop.domain.checks import lint
from taskloop.domain.plan.matchers import gate_only_criteria


class EngineLand1Test(EngineTest):
    def test_happy_path_lands_and_closes(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertTrue(any(c[:2] == ("comments", "add") and "Reflect (engine)" in c[3] for c in self.bd_calls))
        # the facets of this one run, each of which used to be a run of its own
        self.assertIn(("reviewer", None, "openai"), s.calls)  # every green stage gets a cross-family review
        rv = s.prompts[2]
        self.assertNotIn("git diff HEAD", rv)
        self.assertIn("<diff>\ndiff --git a/f.txt b/f.txt", rv)  # the stage's diff, inline (tl-bxk.10.18)
        for fact in ("exit 0", "wrote f", "evidence", "add f"):
            self.assertIn(fact, rv)
        runs = [json.loads(ln) for ln in (ident.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual((r["bead"], r["outcome"], r["coordinator_session"]), ("t-1", "landed", "sess1234-x"))
        self.assertEqual([x["role"] for x in r["sessions"]], ["planner", "worker", "reviewer"])
        self.assertEqual(r["sessions"][1]["ref"], "ref-write")
        self.assertTrue(any(c[:2] == ("comments", "add") and "trace=" + r["run"] in c[3] for c in self.bd_calls))
        self.assertEqual(r["sessions"][1]["tokens"], {"in": 1000, "cached": 800, "out": 50})
        self.assertEqual((r["stats"]["tokens_in"], r["stats"]["tokens_cached"], r["stats"]["tokens_out"]), (3000, 2400, 150))
        self.assertEqual([(w["write"], w["resumed"], w["input_tokens"]) for w in r["write_rounds"]], [(1, "no", 1000)])
        res = self.eng.result()  # the landed run's stats, trace and log
        self.assertEqual(res["outcome"], "landed")
        self.assertEqual((res["bead"], res["run"], res["log"]), ("t-1", self.eng.log_path.stem, str(self.eng.log_path)))
        self.assertFalse(res["asked"])
        for k in ("minutes", "rounds", "tests_added", "retry_after"):
            self.assertIn(k, res)
        self.assertTrue(self.eng.git("symbolic-ref", "--short", "-q", "HEAD"))  # a landed bead leaves the slot on a branch
        want = json.loads((ident.PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
        self.assertEqual(ident.plugin_version(), want)  # the log and trace record the plugin version
        self.assertIn(f"task-loop {want}", self.eng.log_path.read_text())
        self.assertEqual(r["version"], want)

    @unittest.skipIf(os.name == "nt", "the git shim is a shell script")
    def test_a_fetch_that_loses_the_ref_lock_to_a_sibling_worktree_is_tried_again(self):
        # race test (tl-bxk.11.1): worktrees share refs/remotes/origin/main; a fetch at the same time as another
        # process's (a loop's queue, a slot reset, a release) fails "incorrect old value provided" though the ref is
        # then right. The reset's fetch failed the bead; the land's failed it as "fetch or rebase ... failed".
        bin_ = Path(self.tmp.name, "bin")
        bin_.mkdir()
        real = subprocess.run(["which", "git"], capture_output=True, text=True, check=False).stdout.strip()
        mark = Path(self.tmp.name, "fetches")
        (bin_ / "git").write_text(
            f'#!/bin/sh\ncase " $* " in *" fetch "*) echo x >> "{mark}"\n'
            f'  [ $(( $(wc -l < "{mark}") % 2 )) -eq 1 ] && {{ echo "error: fetching ref refs/remotes/origin/main failed: '
            f'incorrect old value provided" >&2; exit 1; }} ;;\nesac\nexec "{real}" "$@"\n')
        (bin_ / "git").chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": "{}{}{}".format(bin_, os.pathsep, os.environ["PATH"])}):
            rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertGreaterEqual(len(mark.read_text().splitlines()), 4)  # reset and land: each lost once, then won
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    def test_a_hung_gate_is_cut_at_gate_timeout_min_and_goes_red(self):
        gate = PY + ' -c "import time; time.sleep(30)"'
        t = time.time()
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=gate,
                                gate_timeout_min=0.02, max_fix_rounds=0)
        self.assertLess(time.time() - t, 20)
        self.assertNotEqual(rc, 0)
        self.assertIn("timed out after 0.02 min", self.eng.log_path.read_text())

    @POSIX_CHECK
    def test_a_gate_killed_by_a_signal_starts_no_fix_round_and_leaves_the_bead_open(self):
        # tl-y35: `gate: exit -15` (the parent stopped it) is the machine's outcome, not the code's
        rc, s = self.run_engine(
            {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
            gate=pyc("import os,signal; os.kill(os.getpid(), signal.SIGTERM)"),
            max_fix_rounds=2,
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])  # no fix round: no second worker call
        self.assertEqual((self.eng.fixes, self.blocked, self.closed), (0, [], []))
        self.assertIn(("update", "t-1", "--status", "open", "--assignee", ""), self.bd_calls)
        log = self.eng.log_path.read_text()
        self.assertEqual([g["exit"] for g in records(self.eng, "gate_end")], [-15])
        self.assertNotIn("gate red", log)

    def test_a_land_lock_wait_is_not_budget(self):
        # tl-y35: 2251 s on the fake clock waiting for the land lock move the budget by exactly that
        eng = self.checks_engine(budget_min=180)
        before = eng.budget.spent_min()

        @contextlib.contextmanager
        def held_by_another(path, holder, waiting=None, timeout=None, check=None):
            must(waiting)("tl-266")
            cast(Any, eng.clock).advance(2251)  # the test's fake clock
            yield path
        eng.os_lock = held_by_another
        with eng.waits.locked("land_lock", Path(self.tmp.name) / "land.lock"):
            pass
        self.assertEqual(eng.waited, 2251)
        self.assertAlmostEqual(before - eng.budget.spent_min(), 2251 / 60, delta=0.5)  # real time moved by ms; no real sleep
        (start,), (end,) = records(eng, "wait_start"), records(eng, "wait_end")
        self.assertEqual(
            (start["holder"], start["id"], end["id"], end["secs"], end["in_budget"]), ("tl-266", end["id"], start["id"], 2251, False)
        )

    def test_the_gate_runs_once_at_land_and_tells_the_push_which_tree_it_gated(self):
        count, seen = Path(self.tmp.name) / "gates", Path(self.tmp.name) / "gated-tree"
        gate = PY + f' -c "open({str(count)!r}, \'a\').write(\'1\')"'
        land = (
            PY
            + (f" -c \"import os; open({str(seen)!r}, 'w').write(os.environ.get('TASK_LOOP_GATED_TREE', ''))\" && git push -q origin "
               f"HEAD:main")
        )
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                gate=gate, land=land)
        self.assertEqual(rc, 0)
        self.assertEqual(count.read_text(), "1")
        self.assertEqual(seen.read_text(), gitrepo.git("rev-parse", "HEAD^{tree}", cwd=str(self.wt)))

    def test_writer_is_told_the_repo_worker_rules_and_never_to_run_the_gate(self):
        self.put_repo_file("docs/agents/worker-rules.md", "RULES-MARK: unity runs on the host\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/worker-rules.md", gate=PY + ' -c "pass"')
        self.assertEqual(rc, 0)
        w = next(p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker")
        self.assertEqual(w.count("RULES-MARK"), 1)  # inlined once, by text
        self.assertNotIn("worker-rules.md", w)  # no path to read (tl-7y6.6.1)
        self.assertNotIn("Read ", w.split("<worker_rules>")[0].rsplit("Your stage", 1)[-1])
        self.assertIn('-c pass`) or the issue tracker (bd)', w)

    def test_wip_from_an_earlier_run_lands_as_one_titled_commit(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from run 1\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        log = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(log, ["Add f (t-1)", "init"])
        self.assertEqual(gitrepo.git("show", "origin/main:g.txt", cwd=str(self.wt)), "from run 1")

    UNITY: ClassVar[Any] = {"cmd": "just unity-check", "why": "it fails on uncommitted client/ changes"}

    def test_a_check_running_a_gate_only_command_is_sent_back_to_the_planner_once(self):
        # lifesim-fld.27.9: a stage check ran `just unity-check`, red by design on the uncommitted tree: stuck, 68 min
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[HAS_F, "env CI=1 just unity-check"])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]}, gate_only=[self.UNITY])
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("just unity-check runs only in the gate at land: it fails on uncommitted client/ changes",
                      s.prompts[1])
        self.assertIn("just unity-check", s.prompts[0])  # the planner is told up front too

    def test_the_gate_command_is_always_gate_only(self):
        bad = dict(PLAN, cases=[{"criterion": "the repo is green", "check": "just  check"}])
        _rc, s = self.run_engine({"plan": [bad, bad]}, gate="just check")
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner"])
        self.assertIn("just check runs only in the gate at land", s.prompts[1])
        self.assertEqual(self.blocked, [])
        self.assertIn("gate", self.said())

    def test_acceptance_that_is_only_the_gate_is_sent_back_naming_the_rule(self):
        # tl-7y6.7.15: the engine runs the gate at land; "just check green" as acceptance proves nothing the land does not
        gate = PY + ' -c "pass"'
        crit = f"`{gate}` passes (green)"
        only = dict(PLAN, cases=[{"criterion": crit, "check": "", "class": "taste"}])
        good = dict(PLAN, cases=[{"criterion": "f.txt exists", "check": HAS_F}])
        rc, s = self.run_engine({"plan": [only, good], "write": [WRITE], "review": [CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("plan-lint rule gate-only-acceptance", s.prompts[1])
        self.assertIn("- " + crit, s.prompts[1])

    def test_acceptance_still_only_the_gate_after_one_rewrite_blocks(self):
        only = dict(PLAN, cases=[{"criterion": "Done when: just check is green", "check": HAS_F}])
        _rc, s = self.run_engine({"plan": [only, only]}, gate="just check")
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner"])
        self.assertEqual(self.blocked, [])
        self.assertIn("gate-only-acceptance", self.said())

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
        self.assertEqual(gate_only_criteria(cases(*bad, *ok), cfg), bad)
        self.assertEqual(gate_only_criteria(cases("just check passes"), cfg_with()), [])

    def test_gate_only_checks_match_a_command_not_a_longer_name_or_an_argument(self):
        cfg = cfg_with(gate="just check", gate_only=["just unity-check", self.UNITY])
        bad = ["just check", "env CI=1 just unity-check --fast", "nice just check"]
        ok = [HAS_F, "just check-fmt", "just unity-checks", "grep 'just check' AGENTS.md", "just fmt"]
        got = lint.gate_only_checks(dict(PLAN, risks=[{"what": "x", "check": c} for c in bad + ok]), cfg)
        self.assertEqual([c for c, _ in got], bad)
        self.assertEqual(lint.gate_only_checks(dict(PLAN, risks=[{"what": "x", "check": "just check"}]),
                                                 cfg_with()), [])

    def test_the_planner_gets_the_repo_rules_and_is_told_the_engine_owns_the_gate(self):
        _rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/codex.md", gate="just check", max_fix_rounds=0)
        self.assertNotIn("codex.md", s.prompts[0])
        self.assertIn("never put `just check` in a stage", s.prompts[0])

    def test_two_accepted_requirements_in_conflict_are_still_a_decision_ask(self):
        self.asks_the_owner("R3 says keep saves forever, R7 says drop them after a week: which wins?")

    @no_repo
    def test_check_timeout_defaults_to_60_min_and_the_gate_to_90(self):
        self.assertEqual((EngineConfig().check_wall_min, EngineConfig().gate_timeout_min), (60, 90))

    def test_sigterm_landing_inside_popen_still_stops_the_new_child(self):
        # tl-10s: the stop arrived before Popen() returned (a loaded machine runs the check ahead of the engine), the handler's
        # raise left the constructor, and the check's whole tree ran on unowned
        class SignalledPopen(subprocess.Popen):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                os.kill(os.getpid(), signal.SIGTERM)
                for _ in range(100):  # a Python handler runs between bytecodes of this thread: give it its turn here
                    time.sleep(0.001)

        pidfile = Path(self.tmp.name, "child.pid")
        eng = self.checks_engine()
        with self.stoppable(), mock.patch.object(subprocess, "Popen", SignalledPopen), self.assertRaises(engine.Blocked) as cm:
            eng.sh(shlex.split(self.spawn(pidfile)))
        self.assertEqual(cm.exception.kind, oc.Kind.PAUSE_KILLED)
        self.assertDead(self.child_of(pidfile))

    def test_sigterm_during_the_land_gate_stops_it_and_pushes_nothing(self):
        pidfile = Path(self.tmp.name, "child.pid")
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                    gate=self.spawn(pidfile, term=True))
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())
        self.assertDead(self.child_of(pidfile))
        self.assertEqual(self.closed, [])
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "")
        self.assertEqual(gitrepo.git("status", "--porcelain", cwd=str(self.wt)), "")

    def test_a_stop_during_the_push_waits_for_it_and_the_bead_lands(self):
        # a stop between the push and cmd_land left a landed bead failed, and the loop reopened it
        with self.stoppable():
            rc, _ = self.run_engine(
                {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                land=pyc(
                    "import os,signal,subprocess,sys,time; os.kill(os.getppid(), signal.SIGTERM); time.sleep(0.3); "
                    "sys.exit(subprocess.call(['git', 'push', '-q', 'origin', 'HEAD:main']))"
                ),
            )
        self.assertEqual(rc, 0)
        self.assertEqual(self.eng.result()["outcome"], "landed")
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(self.blocked, [])

    def test_a_stop_while_the_land_is_recorded_still_closes_it_landed(self):
        def stop_at_the_land_record(*argv):
            if argv[:2] == ("provenance", "record") and "land" in argv:
                os.kill(os.getpid(), sig.SIGTERM)
            return mock.Mock(returncode=0, stdout="", stderr="")
        with self.stoppable(), self.store.stub(bd_fn=stop_at_the_land_record):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual((rc, self.eng.result()["outcome"]), (0, "landed"))
        self.assertEqual(self.blocked, [])

    def test_a_stop_during_a_rejected_push_stops_after_it(self):
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                    land=pyc("import os,signal,sys,time; os.kill(os.getppid(), signal.SIGTERM); time.sleep(0.3); "
                                             "print('! [rejected] (fetch first)', file=sys.stderr); sys.exit(1)"))
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())

    def test_a_rerun_after_a_red_land_gate_lands_the_reviewed_work_once(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=FALSE, max_fix_rounds=0)
        self.assertEqual(rc, 2)
        self.assertIn("gate red", self.blocked[0])
        first = gitrepo.git("rev-parse", "task/t-1", cwd=str(self.wt))
        self.assertEqual(gitrepo.git("show", "task/t-1:f.txt", cwd=str(self.wt)), "d2")
        idle = dict(WRITE, summary="re-proved, no change")
        with mock.patch.object(fake_route.Script, "reply", self.no_write(fake_route.Script.reply)), \
                self.store.stub(comments=[{"author": "denis", "text": "Rerun it."}]):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [idle], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertEqual(gitrepo.git("rev-list", "--count", "origin/main", f"^{first}~1", cwd=str(self.wt)), "1")
        subjects = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)
        self.assertFalse(any(x.startswith("wip") for x in subjects))

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
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate="kill -TERM $PPID; sleep 5")
        self.assertEqual(rc, 2)
        self.assertEqual(self.checkpoint()["step"], "land")
        rc, s = self.run_engine({})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls, [])
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    def test_a_red_gate_replans_with_its_output_and_keeps_the_accepted_stages(self):
        red = PY + ' -c "import sys; print(\'RS0016 ContentPack ctor\'); sys.exit(1)"'
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=red)
        self.assertEqual(rc, 2)  # two fix rounds could not make it green: the next run re-plans with the gate's output
        self.assertEqual(self.checkpoint()["step"], "gate-red")
        fix = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="reconcile the API file")])
        with self.store.stub(comments=[{"author": "denis", "text": "Main moved; reconcile it."}]):
            rc, s = self.run_engine({"plan": [fix], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("already accepted", s.prompts[0])
        self.assertIn("RS0016 ContentPack ctor", (self.eng.run_dir / "replan.md").read_text())

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
        self.assertEqual(rc, 2)
        self.assertIsNone(self.ask())  # tl-7y6.2.2: the refusal is a machine fault; the checkpoint is what resumes the run
        ck = self.checkpoint()
        self.assertEqual((ck["step"], ck["branch"]), ("land", gitrepo.git("symbolic-ref", "--short", "HEAD", cwd=str(self.wt))))
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])  # the fix round again, no plan
        self.assertIn("conflict", s.prompts[0])

    def test_a_red_gate_goes_to_a_fix_round_and_lands(self):
        gate = PY + ' -c "import sys; t=open(\'f.txt\').read().strip(); print(\'gate saw\', t); sys.exit(1 if t == \'d2\' else 0)"'
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "worker", "reviewer"])
        fix = s.prompts[3]
        self.assertIn("gate saw d2", fix)
        self.assertIn("fix", s.prompts[4].lower())
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")
        subjects = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)

    def test_a_gate_fix_brief_has_the_gate_error_lines_its_log_and_the_engine_reruns_the_gate(self):
        gate = PY + (' -c "import sys; t=open(\'f.txt\').read().strip(); '
                     '[print(\'error E%03d: gate no\' % i) for i in range(18) if t == \'d2\']; '
                     'sys.exit(1 if t == \'d2\' else 0)"')
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        fix = s.prompts[3]
        for i in range(18):
            self.assertIn(f"error E{int(i):03d}: gate no", fix)
        self.assertRegex(fix, r"log: \S+gate\.r1\.log")
        self.assertIn("the engine re-runs them; fix from the output above", fix)

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
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("conflict", s.prompts[3])
        log = gitrepo.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(log[:2], ["Add f (t-1)", "theirs"])
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")

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
        return pyc(f"open(r'{log}','a').write('x')"), log

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
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("conflict", s.prompts[3])
        rounds = self.checks_records()
        self.assertEqual(len(rounds), 2)  # the stage, then the conflict fix
        fix = {i["id"]: i for i in rounds[1]["run"]["results"]}
        self.assertEqual(fix[engine.Engine.MARKERS]["status"], "passed")
        self.assertEqual(fix["build"]["status"], "passed")
        for skipped in ("unit", HAS_F, stage_check):
            self.assertEqual((fix[skipped]["status"], fix[skipped]["why"]), ("skipped", "conflict_fix"), skipped)
        self.assertEqual((len(build_log.read_text()), len(unit_log.read_text()), len(stage_log.read_text())), (2, 1, 1))
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")

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
        self.assertEqual(recs[1][engine.Engine.MARKERS], "failed")  # the marker check judged it, not a stage check
        self.assertEqual(rc, 0, self.blocked)

    @ENGINE_BASH
    def test_a_red_gate_after_a_conflict_fix_still_gets_a_fix_round_and_the_gate_ran_once_on_the_result(self):
        flag = Path(self.tmp.name, "gate-ran")
        gate = f"{PY} -c \"import os,sys; g=r'{flag}'; r=os.path.exists(g); open(g,'a').write('x'); sys.exit(0 if r else 1)\""
        rc, s = self.conflict_run({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)  # the stage, the conflict fix, the gate fix
        self.assertEqual(self.eng.fixes, 2)
        self.assertEqual(len(flag.read_text()), 2)  # red once, then green: one gate run per land try

    @ENGINE_BASH
    def test_the_fix_cap_stays_two_after_a_conflict_fix(self):
        rc, s = self.conflict_run({"plan": [PLAN], "write": [WRITE] * 4, "review": [CLEAN] * 4}, gate=FALSE)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)  # the stage, then 2 fix rounds: the conflict fix and one gate fix
        self.assertIn("2 fix rounds", self.blocked[0])

    def test_push_race_retry_keeps_one_land_lock_and_lands(self):
        rc, events, state = self.run_push_race()
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(events, ["enter", "fetch", "rebase", "gate", "push",
                                  "fetch", "rebase", "checks", "gate", "push", "exit"])
        self.assertEqual(state["pushes"], 2)
        self.assertEqual(self.eng.result()["outcome"], "landed")
        self.assertTrue(self.closed[0].startswith("merged "))
        self.assertEqual(gitrepo.git("show", "origin/main:a.txt", cwd=str(self.wt)), "concurrent 1")
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertEqual(gitrepo.git("rev-parse", "HEAD", cwd=str(self.wt)),
                         gitrepo.git("rev-parse", "main", cwd=str(self.race_origin)))

    def test_push_race_retries_use_input_cache(self):
        counts = {key: Path(self.tmp.name, key) for key in ("changed", "same", "whole", "uncached", "stage", "case", "conservative")}

        def bump(key):
            return PY + f' -c "open({str(counts[key])!r}, \'a\').write(\'1\')"'

        checks = [{"id": key, "cmd": bump(key), "group": "tests", "inputs": [path], "inputs_only": True}
                  for key, path in (("changed", "a.txt"), ("same", "f.txt"))]
        checks += [{"id": "whole", "cmd": bump("whole"), "group": "tests"},
                   {"id": "uncached", "cmd": bump("uncached"), "group": "tests", "cache": False},
                   {"id": "conservative", "cmd": bump("conservative"), "group": "tests", "inputs": ["f.txt"]}]
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[bump("stage")])],
                    cases=[{"criterion": "case", "check": bump("case"), "class": "test", "proved_by": "check"}])
        rc, events, state = self.run_push_race(checks=checks, plan=plan)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual({key: path.read_text() for key, path in counts.items()},
                         {key: "1" if key == "same" else "11" for key in counts})
        cached = {c.id for c in state["results"][0] if c.cached}
        self.assertEqual(cached, {"same"})

    def push_race_failure_path_cell(self, failure, after):
        rc, events, state = self.run_push_race(failure=failure)
        self.assertEqual(rc, 2)
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual(events.count("exit"), 1)
        self.assertFalse(self.eng.landed_sha)
        self.assertEqual(events[-2:] if after else events[-1:], ["exit", after] if after else ["exit"])
        self.assertEqual(state["pushes"], 2 if failure in ("push", "network", "stop") else 1)

    def test_push_race_failure_fix_lands_after_the_lock_is_released(self):
        rc, events, _state = self.run_push_race(failure="checks_fixed")
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(events.count("enter"), 2)
        self.assertEqual(events.count("exit"), 2)
        self.assertEqual(events[events.index("fix:verify") - 1], "exit")
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")
        self.assertEqual(self.eng.result()["outcome"], "landed")

    def push_race_exhausted_cell(self, failure):
        rc, events, state = self.run_push_race(failure=failure, resume_failed_fix=True,
                                              max_rounds=1, max_check_tries=1)
        self.assertEqual(state["fix_result"], "replan")
        self.assertEqual(state["first_rc"], 2)
        self.assertEqual(rc, 2, self.blocked)
        self.assertIn("validation fix did not pass", state["first_blocked"])
        self.assertEqual(state["checkpoint"]["step"], "land-verify-red")
        self.assertTrue(state["checkpoint"]["closed"])
        self.assertIn("still red" if failure == "checks_exhausted" else "a high fix",
                      state["checkpoint"]["feedback"])
        self.assertTrue(self.eng.resumed)
        self.assertEqual(state["resume_calls"], ["planner", "worker"] +
                         (["reviewer"] if failure == "review_exhausted" else []))
        self.assertEqual(len(state["resume_checks"]), 1)
        self.assertEqual(any(c.status == "failed" for c in state["resume_checks"][0]),
                         failure == "checks_exhausted")
        self.assertEqual(state["pushes"], 1)  # only the initial, rejected push
        self.assertEqual(state["gates"], 1)  # a green gate cannot accept the failed fix
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual(events.count("exit"), 1)
        self.assertEqual(events[-2:], ["exit", "fix:verify"])
        self.assertFalse(self.eng.landed_sha)
        self.assertNotEqual(self.eng.result()["outcome"], "landed")
        self.assertFalse(self.closed)
        self.assertEqual(self.lands, [])
        self.assertEqual(gitrepo.git("show", "main:a.txt", cwd=str(self.race_origin)), "concurrent 1")
        self.assertEqual(gitrepo.git("ls-tree", "--name-only", "main", "f.txt", cwd=str(self.race_origin)), "")

    def push_race_interrupted_cell(self, interruption, role):
        gate = PY + ' -c "pass"'
        with self.stoppable():
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
        self.assertEqual(rc, 2, self.blocked)
        self.assertEqual(
            bool(seen.get("fix_initialized")), role in ("worker", "reviewer", "transition", "failed_checks")
        )  # a flag: the stop waits for a safe point
        self.assertTrue(seen.get("interrupted"))
        if role in ("worker", "reviewer", "transition", "failed_checks"):
            self.assertEqual(events[-2:], ["exit", "fix:verify"])
        else:
            self.assertEqual(events[-1], "exit")
            self.assertNotIn("fix:verify", events)
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual(events.count("exit"), 1)
        self.assertEqual(race["pushes"], 1)
        self.assertFalse(self.eng.landed_sha)
        self.assertEqual(len(self.closed), closed_before)
        self.assertEqual(self.lands, [])

    def recover_red(self, seen, role, recovery, closed_before, gate):
        ck = self.checkpoint()
        self.assertTrue(ck["closed"])
        self.assertEqual(ck["step"], "land-verify-red")
        if role not in ("worker", "reviewer"):
            self.assertIn("retry check", ck["pending_land_validation"])
            seen["failure"] = ck["pending_land_validation"]
        self.assertEqual(ck["feedback"], seen["failure"])
        self.assertEqual(ck["pending_land_validation"], seen["failure"])
        red_plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])]) if role != "reviewer" else PLAN
        red_review = review(findings=[finding("high")]) if role == "reviewer" else CLEAN
        with self.store.stub(comments=[{"author": "owner", "text": "Recover validation."}]):
            rc, script = self.run_engine({"plan": [red_plan], "write": [WRITE], "review": [red_review]},
                                         gate=gate, max_rounds=1, max_check_tries=1, max_replans=1)
        self.assertEqual(rc, 2, self.blocked)
        self.assertTrue(self.eng.resumed)
        self.assertEqual([c[0] for c in script.calls], ["planner", "worker"] + (["reviewer"] if role == "reviewer" else []))
        self.assertEqual(len(recovery.checks_run), 1)
        self.assertEqual(any(c.exit for c in recovery.checks_run[0]), role != "reviewer")
        self.assertIn(seen["failure"], self.checkpoint()["pending_land_validation"])
        self.assertEqual(self.checkpoint()["step"], "land-verify-red")
        self.assertFalse(recovery.pushes)
        self.assertFalse(self.eng.landed_sha)
        self.assertEqual(len(self.closed), closed_before)
        self.assertEqual(self.lands, [])

    def recover_green(self, recovery, closed_before, gate):
        with self.store.stub(comments=[{"author": "owner", "text": "Recover with passing checks and review."}]):
            rc, script = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                         gate=gate, max_rounds=1, max_check_tries=1, max_replans=2)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in script.calls], ["planner", "worker", "reviewer"])
        self.assertEqual(len(recovery.checks_run), 2)
        self.assertTrue(all(c.exit == 0 for c in recovery.checks_run[-1]))
        self.assertEqual(len(recovery.pushes), 1)
        self.assertFalse(self.eng.pending_land_validation)
        self.assertNoCheckpoint()
        self.assertEqual(self.eng.result()["outcome"], "landed")
        self.assertEqual(len(self.closed), closed_before + 1)
        self.assertEqual(len(self.lands), 1)

    def test_push_race_sigterm_during_retry_check_stops_child_and_keeps_barrier(self):
        with self.stoppable():
            rc, events, race = self.run_push_race(failure="checks_stop", check_wall_min=0.03)
        self.assertEqual(rc, 2, self.blocked)
        self.assertIn("stopped (SIGTERM)", self.said())
        self.assertDead(self.child_of(race["pidfile"]))
        self.assertFalse(race["next_check"].exists(), "another check ran after SIGTERM")
        self.assertEqual(events.count("enter"), 1)
        self.assertEqual(events.count("exit"), 1)
        self.assertEqual(events[-1], "exit")
        self.assertEqual(race["pushes"], 1)
        self.assertFalse(self.closed)
        self.assertFalse(self.eng.landed_sha)
        self.assertEqual(self.lands, [])

        env = {"XDG_CONFIG_HOME": race["config_home"], "APPDATA": race["config_home"]}
        with mock.patch.dict(os.environ, env):
            ck = self.checkpoint()
            self.assertTrue(ck["closed"])
            self.assertEqual(ck["step"], "land-verify-red")
            self.assertIn("retry checks", ck["pending_land_validation"])
            self.assertEqual(ck["feedback"], ck["pending_land_validation"])

    def test_land_lock_is_one_per_repo_across_processes(self):
        if os.name == "nt":
            self.skipTest("POSIX flock")
        eng = self.checks_engine()
        probe = ("import fcntl,sys; f=open(sys.argv[1],'a')\n"
                 "try:\n fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\n"
                 "except OSError: print('held')")
        with eng.lander.lock() as path:
            held = subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True, check=False).stdout
        free = subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True, check=False).stdout
        self.assertEqual((held.strip(), free.strip()), ("held", "free"))


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
       [(i, r) for i in ("pause", "denial") for r in ("worker", "reviewer")] +
       [("SIGTERM", r) for r in ("worker", "reviewer", "failed_checks", "checkpoint", "transition")])
