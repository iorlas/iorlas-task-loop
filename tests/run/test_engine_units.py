"""Engine tests, part 2: the small classes after EngineTest (failure brief, outcome, delegate launcher, stored briefs, confirms,
validate). Split from test_engine."""

import contextlib
import io
import json
import os
import re
import signal
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import pytest

from taskloop.app.asks import admission
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
import support.paths  # noqa: E402, F401
from support import gitq  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.app.plan.planner import Planner  # noqa: E402
from taskloop.app.slots import config as wslots_config  # noqa: E402
from taskloop.app.track import outcome_line  # noqa: E402
from tlkernel import answers  # noqa: E402
from tlkernel import runoutcome as oc  # noqa: E402
from tlkernel.enums import Result  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.ids import BeadId  # noqa: E402
from tlkernel.kinds import Kind  # noqa: E402
from tlkernel.run import RunReport  # noqa: E402
from tlkernel.schema import unstrict  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import engine_case as T  # noqa: E402
from support.briefs import brief_digest  # noqa: E402
from support.engine_case import BRIEFS, full, stop, stored_brief  # noqa: E402
from support.fakes import as_bead, as_comment  # noqa: E402
from support.spawn import port_git, real_spawner  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.adapters import delegate as lroute  # noqa: E402
from taskloop.app.checks import evidence  # noqa: E402
from taskloop.app.run import (  # noqa: E402
    engine,
    entry,
)
from taskloop.domain.checks import (  # noqa: E402
    durations,
    lint,  # noqa: F401
)
from taskloop.domain.checks.writer_split import WriterSplit  # noqa: E402
from tlkernel.checks import Duration, Durations  # noqa: E402
from tltestkit.cfgs import cfg_with  # noqa: E402
from tltestkit.checks import res  # noqa: E402
from tltestkit.narrow import must  # noqa: E402
from tltestkit.plans import CLEAN, PLAN, WRITE, finding, review, verdict  # noqa: E402
from tltestkit.shellkit import sh, shown  # noqa: E402


class FailureBriefAndDurations(Case):
    FIX = Path(__file__).parents[1] / "fixtures" / "checks"

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "cfg"),
                                                "APPDATA": str(self.home / "cfg")})
        self.env.start()
        self.run_dir = self.home / "run"
        (self.run_dir / "checks").mkdir(parents=True)
        for f in self.FIX.glob("*.log"):
            (self.run_dir / "checks" / f.name).write_text(f.read_text())

    def teardown_method(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_analyzer_noise_is_dropped_and_the_real_error_comes_first(self):
        out = evidence.failure_brief([res(cmd="c", exit=1, log="checks/unity-analyzers.log")], self.run_dir, lines=2)
        assert "error MA0051" in out
        assert "UAC0005" not in out

    def test_zero_errors_line_is_not_a_hit(self):
        out = evidence.failure_brief([res(cmd="c", exit=1, log="checks/unity-analyzers.log")], self.run_dir)
        assert out.count("0 Error(s)") == 1  # only as the log's last line, never ranked as an error

    def test_a_timeout_says_so_and_keeps_the_logs_last_line(self):
        out = evidence.failure_brief([res(cmd="just check", exit=124, secs=600, log="checks/timeout.log")], self.run_dir)
        assert "timed out after 600 s" in out
        assert "(timed out after 600 s: the engine stopped it" in out
        killed = evidence.failure_brief([res(cmd="just check", exit=-9, secs=30, log="checks/timeout.log")], self.run_dir)
        assert "timed out after 30 s" in killed

    def test_a_missing_log_says_none_and_a_long_cmd_is_cut(self):
        out = evidence.failure_brief([res(cmd="x" * 500, exit=1, tail="boom: error")], self.run_dir)
        assert "log: none" in out
        assert "x" * 301 not in out

    def test_the_last_traceback_frame_is_kept(self):
        (self.run_dir / "tb.log").write_text(
            'Traceback (most recent call last):\n  File "a.py", line 1, in <module>\n    f()\n'
            '  File "b.py", line 9, in f\n    g()\nValueError: bad\n')
        out = evidence.failure_brief([res(cmd="c", exit=1, log="tb.log")], self.run_dir)
        assert 'File "b.py", line 9, in f\n    g()' in out

    def _history(self, *runs):
        h = Durations()
        for cmd, secs in runs:
            h = durations.merged(h, [Duration(step=cmd, exec_seconds=secs)])
        return durations.seconds(h)

    def test_durations_keep_the_longest_pass_and_whitespace_does_not_split_a_command(self):
        secs = self._history(("just  unity-analyzers", 140), ("just unity-analyzers", 9), ("just fmt", 3))
        assert secs["just unity-analyzers"] == 140
        assert secs["just fmt"] == 3
        split = WriterSplit(cfg_with(writer_check_max_s=60), secs)
        assert split.engine_only("just unity-analyzers")
        assert not split.engine_only("just fmt")

    def test_check_build_and_dotnet_commands_without_history_are_engine_only(self):
        split = WriterSplit(cfg_with(writer_check_max_s=60), {})
        for cmd in ("just check", "dotnet test", "dotnet build", "just build"):
            assert split.engine_only(cmd), cmd

    def test_engine_recipes_are_the_bare_just_recipes_of_checks_and_gate_the_writer_must_not_run(self):
        cfg = cfg_with(writer_check_max_s=60, gate="just check", checks=[
            {"id": "slow", "cmd": "just slow", "group": "tests"}, {"id": "fmt", "cmd": "just fmt", "group": "static"},
            {"id": "u", "cmd": "just unity-tests", "group": "tests", "writer": False},
            {"id": "w", "cmd": "make test", "group": "tests", "writer": False}])
        assert WriterSplit(cfg, {"just slow": 300, "just fmt": 1}).engine_recipes() == ["check", "slow", "unity-tests"]

    def test_a_check_says_writer_true_or_its_own_cut_and_that_beats_the_global_one(self):
        cfg = cfg_with(writer_check_max_s=60, checks=[
            {"id": "analyzers", "cmd": "just unity-analyzers", "group": "static", "writer": True},
            {"id": "slow", "cmd": "just slow", "group": "tests", "writer_check_max_s": 500},
            {"id": "fmt", "cmd": "just fmt", "group": "static", "writer": False}])
        split = WriterSplit(cfg, {"just unity-analyzers": 140, "just slow": 300, "just fmt": 1})
        assert [split.engine_only(c) for c in ("just unity-analyzers", "just slow", "just fmt")] == [False, False, True]


class Outcome(T.EngineTest):
    """What run-task tells the loop (tl loop): landed, parked, paused, failed or taken, as one JSON record."""

    def test_an_owner_ask_is_parked(self):
        self.run_engine({"plan": [dict(PLAN, irreversible="push_shared", question="Old format or new?")]})
        r = self.eng.result()
        assert (r.outcome, r.asked) == ("parked", True)

    def test_a_lane_out_for_long_is_paused_with_the_time_the_lane_is_back(self):
        due = time.time() + 3 * 3600
        self.run_engine({"plan": [PLAN], "write": [stop("rate_limited", at=due, say="out")]})
        r = self.eng.result()
        assert r.outcome == "paused"
        assert self.eng.retry_after == pytest.approx(due, abs=1)

    def test_a_logged_out_worker_is_paused_with_no_time(self):
        out = stop("logged_out", family="claude", say="Failed to authenticate")
        self.run_engine({"plan": [out]})
        r = self.eng.result()
        assert (r.outcome, self.eng.retry_after, r.asked) == ("paused", 0, False)

    def test_an_engine_error_is_failed(self):
        with mock.patch.object(Planner, "plan", side_effect=RuntimeError("boom")):
            self.run_engine({})
        r = self.eng.result()
        assert r.outcome == "failed"
        assert "boom" in r.why

    def main(self, outcome_file, **kw):
        a = mock.Mock(id="t-1", branch=None, pr=None, worktree=str(Path(self.tmp.name, "slot")), slot=None, dry_run=False, fresh=False,
                      quiet=True, outcome_file=str(outcome_file))
        Path(a.worktree).mkdir(exist_ok=True)
        out = io.StringIO()
        with contextlib.chdir(self.wt), redirect_stdout(out), mock.patch.object(signal, "signal"):  # pyrefly: ignore[missing-attribute]
            rc = entry.main(a, self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())  # pyrefly: ignore[missing-attribute]
        last = json.loads(out.getvalue().strip().splitlines()[-1])
        return rc, json.loads(Path(outcome_file).read_text()), last

    def test_run_task_writes_the_outcome_file_and_ends_with_it_as_a_json_line(self):
        f = Path(self.tmp.name, "out.json")
        made = mock.Mock()
        made.return_value.run.return_value = 0
        made.return_value.result.return_value = RunReport(outcome=Result.LANDED, bead=BeadId("t-1"))
        with mock.patch.object(admission, "admit", return_value=(True, "")), mock.patch.object(entry, "Engine", made):
            rc, rec, last = self.main(f)
        assert (rc, rec["outcome"], last["outcome"]) == (0, "landed", "landed")

    def test_a_hand_run_pause_prints_the_exact_resume_time_and_ends_with_the_outcome(self):
        due = time.time() + 1800
        made = mock.Mock()
        made.return_value.retry_after = due
        made.return_value.run.return_value = 2
        made.return_value.result.return_value = RunReport(outcome=Result.PAUSED, bead=BeadId("t-1"),
                                                                  why="paused: no lane for write until 09:36")
        a = mock.Mock(id="t-1", branch=None, pr=None, worktree=str(Path(self.tmp.name, "slot")), slot=None, dry_run=False, fresh=False,
                      quiet=True, outcome_file=None)
        Path(a.worktree).mkdir(exist_ok=True)
        out = io.StringIO()
        with mock.patch.object(admission, "admit", return_value=(True, "")), mock.patch.object(entry, "Engine", made), \
                contextlib.chdir(self.wt), redirect_stdout(out), mock.patch.object(signal, "signal"):  # pyrefly: ignore[missing-attribute]
            entry.main(a, self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())  # pyrefly: ignore[missing-attribute]
        lines = out.getvalue().strip().splitlines()
        assert json.loads(lines[-1])["outcome"] == "paused"  # the loop reads the last line: still the outcome
        assert any(
                "PAUSED t-1: the lane is back at {}; rerun then: tl run-task t-1".format(
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due))
                )
                in ln
                for ln in lines
            ), lines

    def test_a_pause_with_no_time_says_so(self):
        assert "no time" in outcome_line.pause_line(RunReport(outcome=Result.PAUSED, bead=BeadId("t-1")), 0)
        assert outcome_line.pause_line(RunReport(outcome=Result.LANDED, bead=BeadId("t-1")), 0) == ""

    def test_a_refused_claim_is_taken_and_keeps_exit_1(self):
        f = Path(self.tmp.name, "out.json")
        with mock.patch.object(admission, "admit", return_value=(False, "claimed by denis")):
            rc, rec, _last = self.main(f)
        assert (rc, rec["outcome"]) == (1, "taken")
        assert "denis" in rec["why"]


class DelegateLauncher(T.EngineTest):

    def test_a_review_from_the_writers_family_pauses_the_step_and_is_not_taken(self):  # tl-9un.15
        same = full(CLEAN, "r", family="openai", flag="same_family")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [same]})
        assert rc != 0
        assert not self.closed
        assert all(r.reviewer_other_family for r in s.requests if r.role == "reviewer")
        assert not any("same family" in str(c) for c in self.bd_calls if c[:2] == ("comments", "add"))

    # lifesim-d5f.58 2026-10-21: a resumed Codex writer answered lane_out for an hour and the bead paused; delegate never
    # switches lanes on a resume, but a fresh call gets the role's next rung (Sonnet on the claude lane) at once
    OUT_LONG = stop("rate_limited", at=time.time() + 3600, say="cannot continue t now")
    # delegate says the writer fell back off its first lane (to xai, so the reviewer, claude, is another family)
    FRESH = full(WRITE, "w2", fallback=True, first_lane="OPENAI_SUBSCRIPTION", family="xai")

    def test_a_resumed_write_whose_lane_is_out_pauses(self):
        rc, script = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_L],
                                      "review": [review(unmet=["more"])]})
        assert rc == 2
        assert [r.thread for r in script.requests if r.role == "worker"] == ["writer", "writer"]
        assert [bool(r.delta_file) for r in script.requests if r.role == "worker"] == [False, True]
        assert self.eng.retry_after > 0

    # tl-bxk.10.5 2026-10-21: after a real outage the Sonnet thread stayed the writer for every later round of
    # lifesim-fld.27.7, d5f.33, 1eg2 and d5f.54 while Codex was usable again
    BACK = full(WRITE, "w3", family="openai", lane="OPENAI_SUBSCRIPTION", model="gpt")
    OUT_L: ClassVar[Any] = dict(OUT_LONG, lane="OPENAI_SUBSCRIPTION")






    def test_the_first_choice_writer_still_resumes_and_no_status_is_read(self):
        with mock.patch.object(lroute, "status_json") as st:
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE, WRITE],
                                     "review": [review(unmet=["more"]), review(unmet=["more"]), CLEAN]})
        assert rc == 0, self.blocked
        assert [c[1] for c in s.calls if c[0] == "worker"] == [None, "ref-write", "ref-write"]
        st.assert_not_called()


    # contract 4: an answer that picked a lane says whether it is a fallback (and from which first lane, when it can)
    SONNET_FB: ClassVar[Any] = dict(FRESH, rung=1, fallback=True, fallback_reason="ceiling", first_lane="OPENAI_SUBSCRIPTION")
    CODEX_FIRST: ClassVar[Any] = dict(BACK, rung=0, fallback=False, fallback_reason=None)
    no_checks: ClassVar[Any] = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[])])  # FRESH writes no f.txt




    def test_the_answer_a_first_choice_answer_is_resumed(self):
        with mock.patch.object(lroute, "status_json") as st:
            rc, s = self.run_engine({"plan": [self.no_checks], "write": [self.CODEX_FIRST, self.CODEX_FIRST],
                                     "review": [review(unmet=["more"]), CLEAN]})
        assert rc == 0, self.blocked
        assert [c[1] for c in s.calls if c[0] == "worker"] == [None, "w3"]
        st.assert_not_called()

    def test_lanes_read_the_status_lanes(self):
        raw = {"OPENAI_SUBSCRIPTION": {"out": True, "reason": "limit", "out_until": 90.0}, "X": {"out": False}, "Y": {}}
        with mock.patch.object(lroute, "status_json", return_value={"v": 1, "lanes": raw}):
            want = [lroute.Lane("OPENAI_SUBSCRIPTION", False, "limit", 90.0), lroute.Lane("X", True), lroute.Lane("Y", None)]
            assert lroute.lanes() == want
            assert lroute.lane("X") == lroute.Lane("X", True)
            assert lroute.lane("NOPE") is None
        with mock.patch.object(lroute, "status_json", return_value={}):
            assert lroute.lanes() == []

    # lifesim-5ar.6 2026-10-21: the resumed writer's lane_out came with no retry_after, so next was owner, and the bead
    # blocked "needs a human" after 114 min of work
    OUT_OWNER = stop("rate_limited", say="cannot say when OPENAI_SUBSCRIPTION frees")

    def test_a_resumed_write_whose_lane_has_no_time_pauses(self):
        rc, script = self.run_engine({"plan": [PLAN], "write": [WRITE, self.OUT_OWNER],
                                      "review": [review(unmet=["more"])]})
        assert rc == 2
        assert [r.thread for r in script.requests if r.role == "worker"] == ["writer", "writer"]
        assert self.blocked == []
        assert "needs a human" not in self.eng.log_path.read_text()

    def test_a_fresh_write_whose_lane_has_no_time_pauses(self):
        rc, script = self.run_engine({"plan": [PLAN], "write": [self.OUT_OWNER]})
        assert rc == 2
        assert [r.thread for r in script.requests if r.role == "worker"] == ["writer"]
        assert self.blocked == []

    def test_the_writer_brief_has_no_sandbox_or_git_text(self):
        # delegate 0.29 owns what the worker is told about its sandbox, escalation and git (worker-run v2)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        w = next(p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker")
        for gone in ("sandbox", "escalat", "permissions", "You have the host", "no commits", "no pushing"):
            assert gone not in w, gone
        assert "Never run the gate" in w

    def test_a_failure_after_work_still_fails(self):
        worked = stop("worker_failed", tokens={"in": 90000, "cached": 0, "out": 4000}, say="codex: turn failed")
        rc, script = self.run_engine({"plan": [PLAN], "write": [worked]})
        assert [c[0] for c in script.calls].count("worker") == 1
        assert rc == 2
        assert self.said().startswith("Engine failed:"), self.said()

    LOGIN_CLAUDE = "run `claude auth login`"

    def test_a_logged_out_worker_pauses_without_retry_and_leaves_the_bead_open(self):
        out = stop("logged_out", family="claude", say="Failed to authenticate: OAuth session expired", fix=self.LOGIN_CLAUDE)
        rc, s = self.run_engine({"plan": [out, out]})
        assert rc == 2
        assert [c[0] for c in s.calls] == ["planner"]
        assert self.blocked == []
        assert any(c[:1] == ("update",) and "open" in c for c in self.bd_calls)
        assert "claude auth login" in self.eng.log_path.read_text()

    # contract 4: logged_out is lane / needs_owner: the lane waits for its owner, the step never retries it and never asks
    def test_a_logged_out_lane_pauses_with_the_login_fix_and_no_ask(self):
        out = stop("logged_out", family="claude", say="claude is not logged in", fix=self.LOGIN_CLAUDE)
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE]})
        assert rc == 2
        assert [c[0] for c in s.calls].count("worker") == 1
        assert (self.blocked, self.ask()) == ([], None)
        assert any(c[:3] == ("comments", "add", "t-1") and any("run `claude auth login`" in x for x in c)
                            for c in self.bd_calls)

    def test_a_resumed_write_on_a_logged_out_lane_pauses_without_an_ask(self):
        out = stop("logged_out", "ref-write", family="openai", say="codex login", fix="run `codex login`")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, out], "review": [review(unmet=["more"])]})
        assert rc == 2
        assert self.blocked == []
        assert [c[1] for c in s.calls if c[0] == "worker"] == [None, "ref-write"]
        assert any(c[:3] == ("comments", "add", "t-1") and any("run `codex login`" in x for x in c)
                            for c in self.bd_calls)

    def test_every_lane_out_with_no_time_pauses_a_resumed_write_without_an_ask(self):
        none = stop("no_lane", say="every lane is out")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, none],
                                 "review": [review(unmet=["more"])]})
        assert rc == 2
        assert [c[1] for c in s.calls if c[0] == "worker"] == [None, "ref-write"]
        assert self.blocked == []
        assert any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for write" in x for x in c)
                            for c in self.bd_calls)
        assert "needs a human" not in self.eng.log_path.read_text()

    def test_no_lane_needs_owner_even_with_a_predicted_time(self):
        due = time.time() + 3 * 3600
        none = stop("no_lane", at=due, say="every lane is out")
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE, none],
                                 "review": [review(unmet=["more"])]})
        assert rc == 2
        assert self.blocked == []
        assert self.eng.retry_after == 0

    def test_close_with_an_empty_reason_still_closes(self):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who())
        eng.closer.close(oc.make(Kind.FAULT_ENGINE))
        assert "stopped before a reason was recorded" in self.said()  # a fault: the bead stays open, the comment says why

    def test_no_lane_pauses_the_bead_open(self):
        none = stop("no_lane", say="no adequate model")
        rc, _ = self.run_engine({"plan": [none]})
        assert rc == 2
        assert self.blocked == []  # a machine-wide wait is not the bead's fault: it stays open
        assert any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for plan" in x for x in c)
                            for c in self.bd_calls)

    def test_a_lane_out_for_long_pauses_at_once_and_frees_the_slot(self):
        later = stop("rate_limited", at=time.time() + 3 * 3600, say="codex out until 21:00")
        rc, s = self.run_engine({"plan": [PLAN], "write": [later]})
        assert rc == 2
        assert [c[0] for c in s.calls].count("worker") == 1  # no hour of sleeping in the slot
        assert self.blocked == []
        assert any(c[:3] == ("comments", "add", "t-1") and any("paused: no lane for write until" in x for x in c)
                            for c in self.bd_calls)

    def test_a_bead_branch_left_in_another_clean_slot_is_resumed_here(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from slot s2\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): paused", cwd=self.wt)
        sh("git", "checkout", "-q", "--detach", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert gitq.git("show", "origin/main:g.txt", cwd=str(self.wt)) == "from slot s2"
        assert gitq.git("symbolic-ref", "-q", "HEAD", cwd=str(other)) == ""  # s2 let go of the branch

    def test_a_bead_branch_with_uncommitted_work_in_another_slot_is_never_taken(self):
        sh("git", "branch", "task/t-1", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        Path(other, "dirty.txt").write_text("someone's work\n")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 2
        assert shown(other) in self.said()
        assert Path(other, "dirty.txt").exists()

    def test_an_answer_of_another_contract_pauses(self):
        rc, _ = self.run_engine({"plan": [dict(full(PLAN), contract=3)]})
        assert rc == 2
        assert "contract_violation" in self.said()

    def test_a_refused_delegate_blocks_with_its_reason(self):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        with mock.patch.object(dl, "resolve", return_value=dl.Refusal("not_installed")):
            rc = engine.Engine(
                BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who()
            ).run()
        assert rc == 2
        assert "delegate refused the call setup (not_installed" in self.said()


ENGINE_LINE = re.compile(
    r"^(?:- [^:\n]*: )?(?:(?:Lane|Verify|Resume|Look|Land|Plan|Review|Reflect|Ask|Evidence|Follow-up|Parked) \(engine|Blocked:"
    r"|Engine (?:paused|failed):)"
)


class StoredBriefs(Case):
    """tl-7y6.6.2: a sample of the stored run briefs (tests/fixtures/briefs, from ~/.config/task-loop/runs/*/brief.md).
    The briefs were written before the fix and 252 of the 405 carried engine lines; each is read back into notes and comments and
    rebuilt through brief_digest, which must leave none of them in."""

    def test_the_sample_has_engine_lines_to_remove(self):
        names = sorted(p.stem for p in BRIEFS.glob("*.md"))
        assert len(names) >= 30
        assert sum(any(ENGINE_LINE.match(ln) for ln in (BRIEFS / (n + ".md")).read_text().splitlines()) for n in names) > 20
        assert sum(p.stat().st_size for p in BRIEFS.glob("*.md")) <= 200 * 1024

    def test_no_rebuilt_brief_contains_an_engine_prefixed_line_and_none_is_larger(self):
        for p in sorted(BRIEFS.glob("*.md")):
            notes, comments = stored_brief(p.stem)
            bead = {"id": "x", "title": "t", "notes": notes}
            out = brief_digest(must(as_bead(bead)), [as_comment({"author": a, "text": t}) for a, t in comments])
            bad = [ln for ln in out.splitlines() if ENGINE_LINE.match(ln)]
            assert bad == [], p.name
            old = p.read_text(encoding="utf-8")
            assert len(out) <= len(old) + 200, p.name  # the sections rebuilt are never larger than as stored


class Validate(Case):
    def test_schema_subset(self):
        def ok(node, data):
            return answers.check(node, False, data)
        assert ok("review", review(findings=[finding("high")])) == []
        assert ok("review", review(findings=[dict(finding("high"), severity="maybe")]))
        assert ok("review", {"findings": []})
        assert ok("review", dict(CLEAN, unmet="x"))
        assert sorted(answers.NODES) == ["look", "plan", "reflect", "review", "verify", "write"]
        assert ok("verify", {"items": [verdict(1, "settled", "a.cs:3")]}) == []
        assert ok("verify", {"items": [verdict(1, "maybe")]})

    def test_every_contract_sent_is_strict_mode_valid(self):
        """Codex (strict structured output) rejects an object whose `required` misses a property: 53 lifesim runs
        stopped on 'Missing source' / 'Missing accept_files' (2026-10-22)."""
        def walk(sch, path):
            if sch.get("type") == "object":
                assert sch.get("additionalProperties") is False, path
                assert sorted(sch.get("required", [])) == sorted(sch.get("properties", {})), path
                for k, v in sch.get("properties", {}).items():
                    walk(v, path + "." + k)
            if sch.get("type") == "array":
                walk(sch.get("items") or {}, path + "[]")
        for node in answers.NODES:
            for visual in (False, True):
                walk(answers.sent_schema(node, visual), "{}{}".format(node, " (visual)" if visual else ""))

    def test_a_strict_answer_with_null_optionals_validates_against_the_contract(self):
        s = answers.schema_for("review")
        sent = answers.sent_schema("review")
        assert sent["properties"]["accept_files"]["type"] == ["array", "null"]
        got = dict(CLEAN, accept_files=None, reject_files=None,
                   unchecked=[{"what": "x", "kind": "other", "source": None}])
        back = unstrict(got, s)
        assert "accept_files" not in back
        assert "source" not in back["unchecked"][0]
        assert answers.check("review", False, back) == []
        assert answers.schema_for("review") == s  # the contract itself is untouched
