"""ReviewRound: the reviewer's half of a round, from another model family than the writer. Accept is a rule: the checks are green and
nothing blocking is in the review (a high finding with a failure scenario, an unmet requirement). Otherwise the stage goes back to
the writer, until the rounds are used up."""
from collections.abc import Mapping, Sequence
from typing import Any

from taskloop.app.checks.evidence import compact
from taskloop.app.write import review_skip
from taskloop.app.write.state import ACCEPT, AGAIN, REPLAN, StageState
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.prompts.common import LATER_CASES, UNCHECKED_TEXT
from taskloop.domain.prompts.review import acceptance_text, review_prompt
from taskloop.domain.review import findings as fnd
from taskloop.domain.review.followups import FollowKey
from taskloop.domain.review.matchers import AcceptanceItems

CASES_RAN = ("The engine ran every case above with the checks, so a case is never an unchecked item; a case whose "
             "check does not prove its criterion is a finding.\n")


class ReviewRound:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, s: StageState) -> str:
        """-> ACCEPT, AGAIN (sent back) or REPLAN."""
        e = self.e
        if self.skipped(s):
            return ACCEPT
        e.stats["reviews"] += 1
        e.ask_flow.review_cap()
        kinds = e.newfiles.new_by_kind()
        review, _ = e.ai("review", s.name, self.prompt(s, kinds), writer_family=s.wfam, visual=not s.fix and e.pictures.stage_visual(s.st),
                         round=s.rounds + 1, at=(s.sk, s.rounds, s.n), **s.meta)
        e.accepted_new += [p for p in review.get("accept_files") or [] if p in kinds["unexplained"] and p not in e.accepted_new]
        review = self.triage(s, review, kinds)
        self.settle(s, review)
        return self.verdict(s, review)

    def skipped(self, s: StageState) -> bool:
        """True when the stage needs no review: every changed path is mechanical (domain/review/skip.py). A fix round, an item nobody
        has checked or a diff git cannot read is reviewed.
        The skip is the review step's own end: outcome `skipped`, the reasons its detail."""
        e = self.e
        if s.fix or s.wrote_unchecked or e.unchecked:
            return False
        why = review_skip.why(e.git, str(e.wt), e.stage_tree or e.checkout.base_sha(), e.checkout.tree_hash(), e.cfg)
        if not why:
            return False
        said = ", ".join(why)
        e.steps.begin("review", f"{s.name}: review skipped ({said})")
        e.steps.outcome("skipped", said)
        e.log.note(f"{s.name}: review skipped, every changed path is mechanical ({said})")
        e.steps.move("next", "review_skipped", f"{s.name} accepted without review: {said}")
        return True

    def prompt(self, s: StageState, kinds: dict[str, Any]) -> str:
        """The review prompt, then what the review needs of the run (the cases, the unchecked items, what earlier rounds noted)."""
        e, st = self.e, s.st
        gate = f" (`{e.cfg.gate_text}`)" if e.cfg.gate_checks else ""
        text = review_prompt(
            bool(s.fix), s.last, s.state["scope"] if s.fix else "", round_no=s.rounds + 1, prior=e.hand.rounds_text(last=3),
            acceptance=acceptance_text(self.items(s)), brief=e.briefs.text(), plan=e.cases.plan_text(s.i),
            n=s.i + 1, goal=st["goal"],
            work=e.newfiles.stage_work(kinds["unexplained"], kinds["ignored"]), checks=compact(s.run.results), summary=s.w["summary"],
            evidence=e.evidence_dir, gate=gate, added=e.stats["tests_added"], removed=e.stats["tests_removed"])
        where = e.briefing.where("review")
        text += ("\n" + where if where else "") + e.cases.cases_text()
        text += (CASES_RAN if s.last and e.cases.case_checks() else "") + self.open_items(s)
        text += "" if s.last else LATER_CASES
        text += e.routing.ledger().text() + e.hand.seen_lows_text() + e.shared.flakes_text() + UNCHECKED_TEXT
        text += e.judge.look_review(st, s.w, s.fix)
        return text + (e.newfiles.new_files_brief(kinds["unexplained"]) if kinds["unexplained"] else "")

    def items(self, s: StageState) -> list[tuple[str, str]]:
        """The acceptance items the last stage's review maps to evidence (a fix round reviews the fix only)."""
        return AcceptanceItems.split(self.e.scope) if s.last and not s.fix else []

    def open_items(self, s: StageState) -> str:
        """What nobody has checked yet: earlier stages' items and this write's; the review says what is still unproven."""
        items = list({u["what"]: u for u in ([] if s.fix else self.e.unchecked) + s.wrote_unchecked}.values())
        if not items:
            return ""
        return ("\nNobody has checked these yet (earlier stages or the writer could not; the engine's checks above ran "
                "after them); put in your unchecked only what is still unproven:\n"
                + "".join(f"- {u['what']} ({u['kind']})\n" for u in items))

    def triage(self, s: StageState, review: dict[str, Any], kinds: dict[str, Any]) -> dict[str, Any]:
        """The review as the writer is to see it: what is not the writer's to fix taken out (a remark that the goal is met, an item the
        plan's ledger settles, a demand for bd or another operating system, which the engine files as a follow-up bead), later rounds'
        lows dropped, every acceptance item mapped to evidence or a finding, every unexplained new file that no one decided a finding:
        never a silent drop, the writer names it or deletes it."""
        e = self.e
        unmet = fnd.unmet_from(review.get("criteria") or [], review["unmet"])
        routed = fnd.route(unmet, review["findings"], e.routing.ledger())
        for why in routed.dropped:
            e.log.note(f"unmet item dropped: {why}")
        for lo in routed.files:
            if FollowKey.of(e.bead, lo) not in {FollowKey.of(e.bead, x) for x in e.leftovers}:
                e.leftovers.append(lo)
                e.log.note(f"filed as a follow-up bead, not sent back: {lo['title'][:120]}")
        out = fnd.lows_after_first(routed.findings, s.rounds + 1)
        out += fnd.unmapped(self.items(s), review.get("criteria") or [])
        for p in e.newfiles.undecided_new(kinds["unexplained"], review):
            fix = f"decide: unexplained new file {p} (name it in your summary if the task needs it, else delete it)"
            out.append(fnd.engine_finding(p, 0, fix, f"{p} is untracked and no stage lists it, so it is left out of the commit"))
        return dict(review, findings=out, unmet=routed.unmet)

    def settle(self, s: StageState, review: dict[str, Any]) -> None:
        """What the review leaves behind: the unchecked items (lifesim-gfr.31.1: each review re-judges what is open, so its list replaces
        the old; a fix at land reviews only the fix: it adds), the look and link verdicts, the comment, the leftovers, the lows."""
        e = self.e
        checks = s.run.results
        judged = e.cases.out_of_scope(e.cases.engine_unproven(review.get("unchecked") or [], checks))
        e.unchecked = e.unchecked + judged if s.fix else judged
        e.judge.look_judged(review, s.st, s.w, s.fix)
        e.link_check.link_judged(review)
        same = e.last_flag == "same_family"
        if same:
            e.warn(f"{s.name}: the review is from the writer's own model family (no other lane was free)")
        if review["findings"] or review["unmet"] or same:
            lines = [f"{f['file']}:{f['line']} [{f['severity']}] {f['fix']}" for f in review["findings"]]
            lines += ["unmet: " + u for u in review["unmet"]]
            e.comment(f"Review (engine, {s.name}{', same family as the writer' if same else ''}): " + "; ".join(lines))
        e.leftovers += review["leftovers"]
        e.hand.note_lows(review["findings"])

    def verdict(self, s: StageState, review: dict[str, Any]) -> str:
        e = self.e
        if review["question"].strip() and review["decided"].strip():  # lifesim-d5f.58: a fix round, not an ask
            e.log.note(f"{s.name}: the review asked what an accepted requirement decides ({review['decided'][:200]}): sending it back")
            review["unmet"] = review["unmet"] + [
                f"{review['decided']} (an accepted requirement decides it: meet it) {review['question']}"]
        elif review["question"].strip():
            e.steps.outcome("asks", review["question"][:200])
            spec = askspecs.open_question(review["question"], review.get("options"), review.get("owner_cause"))
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=spec)
        blocking = fnd.blocking(review["findings"])
        n = len(blocking)
        said = f"{n} finding{'' if n == 1 else 's'}, {len(review['unmet'])} unmet"
        if not blocking and not review["unmet"]:
            low = len(review["findings"])
            e.steps.outcome("clean", f"{low} note{'' if low == 1 else 's'}" if low else "")
            e.steps.move("next", "accepted", f"{s.name} accepted")
            return ACCEPT
        return self.send_back(s, review, blocking, said)

    def send_back(self, s: StageState, review: dict[str, Any], blocking: Sequence[Mapping[str, Any]], said: str) -> str:
        e = self.e
        e.steps.outcome("sent back", said)
        open_ = review["unmet"] + [f"{f['file']}:{f['line']} {f['fix']}" for f in blocking]
        e.hand.note_round(s.name, s.rounds + 1, "review", s.w["summary"], open_)
        s.rounds += 1
        e.stats["rounds"] += 1
        e.stuck_why = "the review still sends it back: " + "; ".join(open_)
        if s.rounds >= int(e.cfg.max_rounds):
            (e.run_dir / "replan.md").write_text(e.stuck_why)
            e.steps.move("replan", "rounds_used", f"review sent it back: {said}; {s.rounds} rounds used")
            return REPLAN
        s.failed_cmds = None
        e.steps.move("write", "review_sendback", f"{said}: round {s.rounds + 1}")
        s.feedback = ("\nThe reviewer sent the stage back. Fix exactly this:\n{}{}\n".format(
            "".join(f"- unmet: {u}\n" for u in review["unmet"]),
            "".join(f"- {f['file']}:{f['line']} [{f['severity']}] {f['fix']} (scenario: {f['scenario']})\n" for f in blocking)))
        return AGAIN
