"""Verifier: one read-only verifier call before a verify ask; returns the items that still go to the owner. Per item: settled with quoted
evidence drops it, wrong goes to one fix round at land (max_fix_rounds; none left: to the owner, naming the defect), open goes to the
owner. The 2026-10-21 night: three beads (a hand-written .meta against its siblings, a call site and
an evidence file that proved it) each waited hours for an ask a supervisor settled in a minute by reading."""
from typing import Any

from tlkernel import followkeys as followups
from tlkernel import workswitch as switch
from tlkernel.answers import VERDICTS
from tlkernel.reviewkinds import UNCHECKED_KINDS
from tlkernel.stagefacts import RunFacts

from tlwork.review.host import ReviewHand, ReviewPorts
from tlwork.review.state import ReviewLive
from tlwork.review.verify_prompt import VERIFY_PROMPT
from tlwork.work import visual
from tlwork.work.skip import SkipKind

Item = dict[str, Any]
RAISE_KINDS = ("FAULT_BAD_REQUEST", "PAUSE_NETWORK", "PAUSE_KILLED")


def plural(n: int) -> str:
    return "" if n == 1 else "s"


class Verifier:
    def __init__(self, facts: RunFacts, ports: ReviewPorts, live: ReviewLive, hand: ReviewHand) -> None:
        self.facts, self.ports, self.live, self.hand = facts, ports, live, hand

    def run(self, gaps: list[Item]) -> list[Item]:
        """The items that still go to the owner."""
        if not gaps:
            return gaps
        gaps = self.drop_unused(gaps)
        if not gaps:
            return []
        gaps, failed = self.hand.settles.settle(gaps)  # tl-bxk.10.19: what the engine proves itself is never asked
        gaps = self.hand.routing.engine_steps(gaps)
        off = switch.mode(self.facts.cfg.review, self.ports.budget.labels) == "off"
        if gaps and (off or not self.visual()):
            asked = self.defer(gaps, review_off=off and self.visual())
            if failed:  # what the engine itself found wrong still goes back to the writer
                return self.settle_wrong(asked, failed)
            return self.after_clean(asked, self.counts()) if asked else []
        d = self.ask(gaps)
        if d is None:  # no verifier now is no reason to land unchecked: the owner checks them, as before
            return gaps + failed
        still, wrong = self.judge(gaps, d, failed)
        return self.settle_wrong(still, wrong) if wrong else self.after_clean(still, self.counts())

    def visual(self) -> bool:
        """Verify runs only on a visual bead: some plan case is look-objective, taste or show (domain/work/visual.py)."""
        return visual.is_visual((self.hand.plan_data or {}).get("cases") or [])

    def defer(self, gaps: list[Item], review_off: bool = False) -> list[Item]:
        """The items to ask. A bead that is not visual does not run verify: an item about one of its acceptance lines
        is asked, the others land with the bead and go in one follow-up bead tagged `follow-up` (filed at the close). A visual bead with
        engine.review off is deferred the same way (`review_off`): no verifier call, the skip is the step's typed reason and the
        bead's comment names the skipped check."""
        asked = [dict(u, why=u.get("why") or "it names an acceptance criterion")
                 for u in gaps if visual.names_criterion(u["what"], self.hand.scope or "")]
        rest = [u for u in gaps if u not in asked]
        if rest:
            lo = followups.unchecked(self.facts.bead, rest, followups.REVIEW_OFF if review_off else followups.NOT_VISUAL)
            if self.hand.routing.add_leftover(lo):
                self.ports.checkpoints.keep_pending("verify")
            if review_off:
                self.ports.steps.begin("verify", f"{len(rest)} unchecked item(s): verify skipped ({SkipKind.REVIEW_OFF})")
                self.ports.steps.outcome("skipped", SkipKind.REVIEW_OFF)
            self.ports.comment("Verify (engine): " + ("visual check skipped, verify and look did not run because review is off; landed"
                                              if review_off else "not a visual bead, landed")
                      + " with these unchecked, filed as a follow-up: " + "; ".join(u["what"] for u in rest))
            self.ports.steps.move("land", SkipKind.REVIEW_OFF if review_off else "not_visual",
                         f"{len(rest)} item{plural(len(rest))} unchecked, one follow-up bead")
        return asked

    def counts(self) -> str:
        return ", ".join(f"{sum(x['verdict'] == k for x in self.live.verified)} {k}" for k in VERDICTS)

    def drop_unused(self, gaps: list[Item]) -> list[Item]:
        """Items that name a tool the repo does not use are settled as 'not a check here'."""
        unused = [(u, self.hand.settles.unused_tool(u["what"])) for u in gaps]
        for u, ev in unused:
            if ev:
                self.live.add_verified(u, "settled", "not a check here", ev)
        left = [u for u, ev in unused if not ev]
        n_drop = len(gaps) - len(left)
        if n_drop:
            self.ports.steps.move("verify" if left else "land", "not_a_check",
                         f"{n_drop} item{plural(n_drop)} name a tool the repo does not use")
        if n_drop and not left:
            self.note(self.counts(), before=True)
        return left

    def note(self, counts: str, before: bool = False) -> None:
        self.ports.log.note(f"verify: before land: {counts}")
        if before:
            self.ports.comment("Verify (engine): what the workers could not check, before land: " + "; ".join(
                "{}: {}, {}".format(x["verdict"], x["what"], '"{}"'.format(x["evidence"]))
                for x in self.live.verified))

    def ask(self, gaps: list[Item]) -> dict[str, Any] | None:
        """The verifier's answer ({"items": []} when there is nothing to ask); None when no verifier could be had."""
        if not gaps:
            return {"items": []}
        items = "".join(f"{n}. {u['what']} ({u['kind']})\n" for n, u in enumerate(gaps, 1)) + self.ports.judge.look_verify(gaps)
        prompt = VERIFY_PROMPT.format(brief=self.ports.briefs.text(), work=self.hand.settles.work_summary(),
                                      evidence=self.facts.evidence_dir,
                                      checks=self.hand.settles.evidence_text(), where=self.ports.briefing.where("verify"),
                                      items=items) + self.hand.routing.ledger().text()
        try:
            d = self.ports.ai("verify", f"{len(gaps)} unchecked item(s) before land", prompt, writer_family=self.hand.writer_family,
                        items=len(gaps), at=(self.hand.at_stage, 0, 0)).data
        except self.ports.Blocked as b:
            if b.kind.name in RAISE_KINDS:
                raise  # tl-bxk.10.31: the request is malformed for every bead; the network and a kill resume this step, they do not skip it
            self.ports.warn(f"could not self-verify before land, the owner checks every item: {b.why[:300]}")
            return None
        if self.hand.last_flag == "same_family":
            self.ports.warn("the check before land is from the writer's own model family (no other lane was free)")
        return d

    def judge(self, gaps: list[Item], d: dict[str, Any], failed: list[Item]) -> tuple[list[Item], list[Item]]:
        """(items still open for the owner, items found wrong), the verifier's verdict applied to each gap."""
        said: dict[int, Item] = {}
        for a in d["items"]:
            said.setdefault(a["n"], a)
        still: list[Item] = []
        wrong = list(failed)
        for n, gap in enumerate(gaps, 1):
            u = gap
            a = said.get(n) or {"verdict": "open", "evidence": "", "why": "the verifier did not answer it"}
            v, why = a["verdict"], a["why"]
            if v == "settled" and not a["evidence"].strip():
                v, why = "open", "settled without quoted evidence"
            if self.ports.judge.is_look(u):
                v, a, why = self.ports.judge.look_verdict(u, v, a, why)
            kind, source = self.hand.routing.resolve_kind(u, a)
            u = dict(u, kind=kind, source=source)
            route = ""
            if v == "open":
                v, a, why, route = self.hand.routing.route_open(u, a, why)
            self.live.add_verified(u, "open" if route == "unverified" else v, why, a["evidence"])
            if route == "proof":
                wrong.append(dict(u, why=why, proof_round=True))
            elif v != "settled" and route != "unverified":
                (wrong if v == "wrong" else still).append(dict(u, why=why))
        self.note(self.counts())
        self.ports.steps.outcome("wrong" if wrong else "open" if still else "settled", self.counts())
        self.ports.comment("Verify (engine): what the workers could not check, self-verified read-only before land: " + "; ".join(
            "{}: {}, {}".format(x["verdict"], x["what"], ('"{}"'.format(x["evidence"])) if x["verdict"] == "settled" else x["why"])
            for x in self.live.verified))
        return still, wrong

    def after_clean(self, still: list[Item], counts: str) -> list[Item]:
        if still:
            self.ports.steps.move("ask", "verify_open", f"{len(still)} item{plural(len(still))} only the owner can decide")
        elif self.live.unverified:
            n = len(self.live.unverified)
            self.ports.steps.move("land", "unverified", f"{n} item{plural(n)} land unverified, for the owner")
        else:
            self.ports.steps.move("land", "verified", counts)
        return still

    def settle_wrong(self, still: list[Item], wrong: list[Item]) -> list[Item]:
        """Items found wrong go to a fix round; what the fix leaves unproven is routed again, until no fix round is left."""
        if self.hand.fixes >= self.facts.cfg.max_fix_rounds:
            self.ports.steps.move("ask", "verify_wrong", f"{len(wrong)} found wrong, no fix round left")
            return still + [dict(u, why="found wrong: {}; no fix round left".format(u["why"])) for u in wrong]
        self.ports.steps.move("fix", "verify_wrong", f"{len(wrong)} found wrong: " + "; ".join(u["why"] for u in wrong))
        pending = wrong
        while True:
            left = self.fix_round(still, pending)
            pending = [u for u in left if u.get("proof_round")]
            if not pending:
                return left
            if self.hand.fixes >= self.facts.cfg.max_fix_rounds:  # a bead with an unproven checkable item never lands
                raise self.hand.routing.proof_stuck(pending)
            still = [u for u in left if not u.get("proof_round")]
            self.ports.steps.move("fix", "verify_unproven", f"{len(pending)} still unproven after the fix round")

    def fix_round(self, still: list[Item], pending: list[Item]) -> list[Item]:
        """One fix round for the pending items; -> the items still unchecked after it, routed. The pending items stay unchecked in the
        fix's checkpoint: a fix round that pauses resumes at land and verifies them again, never lands them; the fix's review adds
        what it leaves unproven."""
        self.live.unchecked = [u for u in self.live.unchecked if u["kind"] not in UNCHECKED_KINDS] + still + pending
        before = len(self.live.unchecked)
        pending = [dict(u, why=u.get("why") or "add a test or check that proves: {}".format(u["what"])) for u in pending]
        done = self.ports.fixer.fix("verify", "".join("- {}: {}\n".format(u["what"], u["why"]) for u in pending))
        fixed = {u["what"] for u in pending}
        # what the fix's review added stays
        self.live.unchecked = [u for u in self.live.unchecked[:before] if u["what"] not in fixed] + self.live.unchecked[before:]
        left = [u for u in self.live.unchecked if u["kind"] in UNCHECKED_KINDS]
        if done != "accept":
            left += [dict(u, why="found wrong: {}; the fix round did not pass".format(u["why"])) for u in pending]
        return self.hand.routing.route_left(left)
