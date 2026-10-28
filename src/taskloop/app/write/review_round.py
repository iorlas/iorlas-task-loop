"""ReviewRound: the reviewer's half of a round, from another model family than the writer. Accept is a rule: the checks are green and
nothing blocking is in the review (high or medium findings, unmet requirements). Otherwise the stage goes back to the writer, until the
rounds are used up."""
from typing import Any

from taskloop.app.checks.evidence import compact
from taskloop.app.write.state import ACCEPT, AGAIN, REPLAN, StageState
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.prompts.common import LATER_CASES, UNCHECKED_TEXT
from taskloop.domain.prompts.review import review_prompt

CASES_RAN = ("The engine ran every case above with the checks, so a case is never an unchecked item; a case whose "
             "check does not prove its criterion is a finding.\n")


class ReviewRound:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, s: StageState) -> str:
        """-> ACCEPT, AGAIN (sent back) or REPLAN."""
        e = self.e
        e.stats["reviews"] += 1
        e.review_cap()
        kinds = e.new_by_kind()
        review, _ = e.ai("review", s.name, self.prompt(s, kinds), writer_family=s.wfam, visual=not s.fix and e.stage_visual(s.st),
                         round=s.rounds + 1, at=(s.sk, s.rounds, s.n), **s.meta)
        e.accepted_new += [p for p in review.get("accept_files") or [] if p in kinds["unexplained"] and p not in e.accepted_new]
        review = self.triage(s, review, kinds)
        self.settle(s, review)
        return self.verdict(s, review)

    def prompt(self, s: StageState, kinds: dict[str, Any]) -> str:
        """The review prompt, then what the review needs of the run (the cases, the unchecked items, what earlier rounds noted)."""
        e, st = self.e, s.st
        gate = f" (`{e.cfg.gate_text}`)" if e.cfg.gate else ""
        text = review_prompt(
            bool(s.fix), s.last, s.state["scope"] if s.fix else "", brief=e.brief_text(), plan=e.plan_text(), n=s.i + 1, goal=st["goal"],
            work=e.stage_work(kinds["unexplained"], kinds["ignored"]), checks=compact(s.run.results), summary=s.w["summary"],
            evidence=e.evidence_dir, gate=gate, added=e.stats["tests_added"], removed=e.stats["tests_removed"])
        where = e.where("review")
        text += ("\n" + where if where else "") + e.cases_text() + (CASES_RAN if s.last and e.case_checks() else "") + self.open_items(s)
        text += "" if s.last else LATER_CASES
        text += e.deferred_text() + e.hand.seen_lows_text() + e.flakes_text() + UNCHECKED_TEXT + e.look_review(st, s.w, s.fix)
        return text + (e.new_files_brief(kinds["unexplained"]) if kinds["unexplained"] else "")

    def open_items(self, s: StageState) -> str:
        """What nobody has checked yet: earlier stages' items and this write's; the review says what is still unproven."""
        items = list({u["what"]: u for u in ([] if s.fix else self.e.unchecked) + s.wrote_unchecked}.values())
        if not items:
            return ""
        return ("\nNobody has checked these yet (earlier stages or the writer could not; the engine's checks above ran "
                "after them); put in your unchecked only what is still unproven:\n"
                + "".join(f"- {u['what']} ({u['kind']})\n" for u in items))

    def triage(self, s: StageState, review: dict[str, Any], kinds: dict[str, Any]) -> dict[str, Any]:
        """The review with the unmet items the plan's ledger settles dropped (tl-bxk.13.16.1), and every unexplained new file that no one
        decided a finding: never a silent drop, the writer names it or deletes it."""
        e = self.e
        review = dict(review, findings=list(review["findings"]))
        kept = [u for u in review["unmet"] if not e.ledger_route(u)]
        if len(kept) != len(review["unmet"]):
            gone = len(review["unmet"]) - len(kept)
            e.log.note(f"{gone} unmet item{'' if gone == 1 else 's'} dropped: the plan's ledger defers or gives them to the engine: "
                       + "; ".join(u[:80] for u in review["unmet"] if u not in kept))
            review["unmet"] = kept
        for p in e.undecided_new(kinds["unexplained"], review):
            review["findings"].append({"file": p, "line": 0, "severity": "medium", "fix":
                                       f"decide: unexplained new file {p} (name it in your summary if the task needs it, else delete it)"})
        return review

    def settle(self, s: StageState, review: dict[str, Any]) -> None:
        """What the review leaves behind: the unchecked items (lifesim-gfr.31.1: each review re-judges what is open, so its list replaces
        the old; a fix at land reviews only the fix: it adds), the look and link verdicts, the comment, the leftovers, the lows."""
        e = self.e
        checks = s.run.results
        judged = e.out_of_scope(e.engine_unproven(review.get("unchecked") or [], checks))
        e.unchecked = e.unchecked + judged if s.fix else judged
        e.look_judged(review, s.st, s.w, s.fix)
        e.link_judged(review)
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
            spec = askspecs.open_question(review["question"], review.get("options"))
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=spec)
        blocking = [f for f in review["findings"] if f["severity"] in ("high", "medium")]
        n = len(blocking)
        said = f"{n} finding{'' if n == 1 else 's'}, {len(review['unmet'])} unmet"
        if not blocking and not review["unmet"]:
            low = len(review["findings"])
            e.steps.outcome("clean", f"{low} low finding{'' if low == 1 else 's'}" if low else "")
            e.steps.move("next", "accepted", f"{s.name} accepted")
            return ACCEPT
        return self.send_back(s, review, blocking, said)

    def send_back(self, s: StageState, review: dict[str, Any], blocking: list[dict[str, Any]], said: str) -> str:
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
            "".join(f"- {f['file']}:{f['line']} [{f['severity']}] {f['fix']}\n" for f in blocking)))
        return AGAIN
