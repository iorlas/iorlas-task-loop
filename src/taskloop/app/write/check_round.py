"""CheckRound: the engine's checks after a write, outside the writer's sandbox. A red check goes straight back to the writer; a check
the writer calls impossible, red tries used up, or the rounds used up ask for a re-plan."""
from typing import Any

from taskloop.app.checks import evidence as check_evidence
from taskloop.app.write.state import AGAIN, REPLAN, StageState
from taskloop.domain.prompts.write import REPEAT_RED
from taskloop.domain.write.matchers import count_tests


class CheckRound:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, s: StageState) -> str:
        """The round's checks. -> "" when they are green, else AGAIN or REPLAN."""
        e = self.e
        s.acc_first = s.acc_only and not s.acc_first  # once, then the normal order: a check may read what a tests-group check writes
        stage = dict(s.st, checks=s.st["checks"] + (e.case_checks() if s.last else []))
        run = e.run_checks(stage, s.name, acceptance_first=s.acc_first, conflict_fix=s.state.get("conflict_fix"), round=s.rounds + 1,
                           **s.meta)
        s.run, e.last_run = run, run
        e.stores.check_run(e.run_dir.name, None).write(run)
        e.stats["tests_added"], e.stats["tests_removed"] = count_tests(e.task_diff(), e.cfg.test_pattern)
        if e.stats["tests_removed"]:
            e.warn(f"the task's diff removes {e.stats['tests_removed']} tests")
        failed = run.failed
        prev_red, s.red_now = s.red_now, {c.cmd for c in failed}  # the commands red last round (tl-bxk.13.11)
        s.acc_only = bool(failed) and all(c.group == "acceptance" for c in failed)
        wrong = self.flagged(s, failed)
        if wrong:  # a check no code change can satisfy: retrying it is waste, the plan must change
            return self.impossible(s, wrong)
        if failed:
            return self.red(s, run, failed, prev_red)
        s.red = 0
        e.steps.move("review", "checks_green", f"{len(run.passed)} passed")
        return ""

    def flagged(self, s: StageState, failed: list[Any]) -> list[tuple[Any, str]]:
        """[(check, why)]: the red checks the writer called wrong."""
        out = []
        for c in failed:
            why = check_evidence.flagged_why(c, s.w["bad_checks"])
            if why:
                out.append((c, why))
        return out

    def impossible(self, s: StageState, wrong: list[tuple[Any, str]]) -> str:
        e = self.e
        e.stuck_why = "the writer says these stage checks are wrong: " + "; ".join(
            f"`{c.cmd}` (exit {c.exit}): {why}" for c, why in wrong)
        e.warn(f"{s.name}: {e.stuck_why[:300]}")
        e.hand.note_round(s.name, s.rounds + 1, "bad_checks", s.w["summary"], [why for _, why in wrong])
        brief = check_evidence.failure_brief([c for c, _ in wrong], e.run_dir)
        (e.run_dir / "replan.md").write_text(e.stuck_why + "\n\nTheir output:\n" + brief)
        n = len(wrong)
        e.steps.move("replan", "bad_checks",
                     f"the writer says {n} check{'' if n == 1 else 's'} cannot pass: " + "; ".join(why for _, why in wrong))
        return REPLAN

    def red(self, s: StageState, run: Any, failed: list[Any], prev_red: set[str]) -> str:
        e = self.e
        s.red += 1
        s.failed_cmds = [c.cmd for c in failed]
        brief = check_evidence.failure_brief(failed, e.run_dir)
        s.feedback = f"\nThese checks fail (run by the engine, outside your sandbox). Fix exactly this:\n{brief}\n" + e.base_red_text(run)
        again = [c.cmd for c in failed if c.cmd in prev_red and c.id == c.cmd]  # a plan's check, not a repo check
        if again:  # tl-bxk.13.11: lifesim-fdyo tuned contrast to a threshold the plan made up, 3 rounds, 5.98M tokens in one turn
            s.feedback += REPEAT_RED % "\n".join(f"- {c[:200]}" for c in again)
        red_text = f"{len(failed)} failed: {', '.join(c.id[:60] for c in failed)}"
        e.hand.note_round(s.name, s.rounds + 1, "checks_red", s.w["summary"], [c.id for c in failed])
        if s.red < int(e.cfg.max_check_tries):
            e.steps.move("write", "checks_red", red_text)
            return AGAIN
        s.red, s.rounds = 0, s.rounds + 1
        e.stats["rounds"] += 1
        e.stuck_why = f"checks still red after {e.cfg.max_check_tries} tries: {check_evidence.compact(failed)}"
        if s.rounds >= int(e.cfg.max_rounds):
            brief = check_evidence.failure_brief(failed, e.run_dir)
            (e.run_dir / "replan.md").write_text(e.stuck_why + "\n\nTheir output:\n" + brief)
            e.steps.move("replan", "rounds_used", f"{red_text}; {s.rounds} rounds used")
            return REPLAN
        e.steps.move("write", "checks_red", f"{red_text}; round {s.rounds} used")
        return AGAIN
