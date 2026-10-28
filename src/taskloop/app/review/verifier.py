"""Verifier: one read-only verifier call before a verify ask; returns the items that still go to the owner. Per item: settled with quoted
evidence drops it, wrong goes to one fix round at land (max_fix_rounds; none left: to the owner, naming the defect), open goes to the
owner. The 2026-10-21 lifesim night: lifesim-d5f.46 (a hand-written .meta against its siblings), lifesim-fld.26.15 (a call site) and
lifesim-gfr.31.1 (an evidence file that proved it) each waited hours for an ask a supervisor settled in a minute by reading."""
from typing import Any

from taskloop.contracts.answers import VERDICTS
from taskloop.domain.prompts.verify import VERIFY_PROMPT
from taskloop.domain.review.kinds import UNCHECKED_KINDS

Item = dict[str, Any]
RAISE_KINDS = ("FAULT_BAD_REQUEST", "PAUSE_NETWORK", "PAUSE_KILLED")


def plural(n: int) -> str:
    return "" if n == 1 else "s"


class Verifier:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, gaps: list[Item]) -> list[Item]:
        """The items that still go to the owner."""
        e = self.e
        if not gaps:
            return gaps
        gaps = self.drop_unused(gaps)
        if not gaps:
            return []
        gaps, failed = e.settles.settle(gaps)  # tl-bxk.10.19: what the engine proves itself is never asked
        gaps = e.routing.engine_steps(gaps)
        d = self.ask(gaps)
        if d is None:  # no verifier now is no reason to land unchecked: the owner checks them, as before
            return gaps + failed
        still, wrong = self.judge(gaps, d, failed)
        return self.settle_wrong(still, wrong) if wrong else self.after_clean(still, self.counts())

    def counts(self) -> str:
        return ", ".join(f"{sum(x['verdict'] == k for x in self.e.verified)} {k}" for k in VERDICTS)

    def drop_unused(self, gaps: list[Item]) -> list[Item]:
        """Items that name a tool the repo does not use are settled as 'not a check here'."""
        e = self.e
        unused = [(u, e.settles.unused_tool(u["what"])) for u in gaps]
        for u, ev in unused:
            if ev:
                e.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "evidence": ev, "why": "not a check here"})
        left = [u for u, ev in unused if not ev]
        n_drop = len(gaps) - len(left)
        if n_drop:
            e.steps.move("verify" if left else "land", "not_a_check",
                         f"{n_drop} item{plural(n_drop)} name a tool the repo does not use")
        if n_drop and not left:
            self.note(self.counts(), before=True)
        return left

    def note(self, counts: str, before: bool = False) -> None:
        e = self.e
        e.log.note(f"verify: before land: {counts}")
        if before:
            e.comment("Verify (engine): what the workers could not check, before land: " + "; ".join(
                "{}: {}, {}".format(x["verdict"], x["what"], '"{}"'.format(x["evidence"])) for x in e.verified))

    def ask(self, gaps: list[Item]) -> dict[str, Any] | None:
        """The verifier's answer ({"items": []} when there is nothing to ask); None when no verifier could be had."""
        e = self.e
        if not gaps:
            return {"items": []}
        items = "".join(f"{n}. {u['what']} ({u['kind']})\n" for n, u in enumerate(gaps, 1)) + e.judge.look_verify(gaps)
        prompt = VERIFY_PROMPT.format(brief=e.briefs.text(), work=e.settles.work_summary(), evidence=e.evidence_dir,
                                      checks=e.settles.evidence_text(), where=e.where("verify"), items=items) + e.routing.ledger().text()
        try:
            d, _ = e.ai("verify", f"{len(gaps)} unchecked item(s) before land", prompt, writer_family=e.writer_family,
                        items=len(gaps), at=(e.at_stage, 0, 0))
        except e.Blocked as b:
            if b.kind.name in RAISE_KINDS:
                raise  # tl-bxk.10.31: the request is malformed for every bead; the network and a kill resume this step, they do not skip it
            e.warn(f"could not self-verify before land, the owner checks every item: {b.why[:300]}")
            return None
        if e.last_flag == "same_family":
            e.warn("the check before land is from the writer's own model family (no other lane was free)")
        return d

    def judge(self, gaps: list[Item], d: dict[str, Any], failed: list[Item]) -> tuple[list[Item], list[Item]]:
        """(items still open for the owner, items found wrong), the verifier's verdict applied to each gap."""
        e = self.e
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
            if e.judge.is_look(u):
                v, a, why = e.judge.look_verdict(u, v, a, why)
            kind, source = e.routing.resolve_kind(u, a)
            u = dict(u, kind=kind, source=source)
            route = ""
            if v == "open":
                v, a, why, route = e.routing.route_open(u, a, why)
            e.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "open" if route == "unverified" else v,
                               "evidence": a["evidence"], "why": why})
            if route == "proof":
                wrong.append(dict(u, why=why, proof_round=True))
            elif v != "settled" and route != "unverified":
                (wrong if v == "wrong" else still).append(dict(u, why=why))
        self.note(self.counts())
        e.steps.outcome("wrong" if wrong else "open" if still else "settled", self.counts())
        e.comment("Verify (engine): what the workers could not check, self-verified read-only before land: " + "; ".join(
            "{}: {}, {}".format(x["verdict"], x["what"], ('"{}"'.format(x["evidence"])) if x["verdict"] == "settled" else x["why"])
            for x in e.verified))
        return still, wrong

    def after_clean(self, still: list[Item], counts: str) -> list[Item]:
        e = self.e
        if still:
            e.steps.move("ask", "verify_open", f"{len(still)} item{plural(len(still))} only the owner can decide")
        elif e.unverified:
            e.steps.move("land", "unverified", f"{len(e.unverified)} item{plural(len(e.unverified))} land unverified, for the owner")
        else:
            e.steps.move("land", "verified", counts)
        return still

    def settle_wrong(self, still: list[Item], wrong: list[Item]) -> list[Item]:
        """Items found wrong go to a fix round; what the fix leaves unproven is routed again, until no fix round is left."""
        e = self.e
        if e.fixes >= int(e.cfg.max_fix_rounds):
            e.steps.move("ask", "verify_wrong", f"{len(wrong)} found wrong, no fix round left")
            return still + [dict(u, why="found wrong: {}; no fix round left".format(u["why"])) for u in wrong]
        e.steps.move("fix", "verify_wrong", f"{len(wrong)} found wrong: " + "; ".join(u["why"] for u in wrong))
        pending = wrong
        while True:
            left = self.fix_round(still, pending)
            pending = [u for u in left if u.get("proof_round")]
            if not pending:
                return left
            if e.fixes >= int(e.cfg.max_fix_rounds):  # a bead with an unproven checkable item never lands
                raise e.routing.proof_stuck(pending)
            still = [u for u in left if not u.get("proof_round")]
            e.steps.move("fix", "verify_unproven", f"{len(pending)} still unproven after the fix round")

    def fix_round(self, still: list[Item], pending: list[Item]) -> list[Item]:
        """One fix round for the pending items; -> the items still unchecked after it, routed. The pending items stay unchecked in the
        fix's checkpoint: a fix round that pauses resumes at land and verifies them again, never lands them; the fix's review adds
        what it leaves unproven."""
        e = self.e
        e.unchecked = [u for u in e.unchecked if u["kind"] not in UNCHECKED_KINDS] + still + pending
        before = len(e.unchecked)
        pending = [dict(u, why=u.get("why") or "add a test or check that proves: {}".format(u["what"])) for u in pending]
        done = e.fixer.fix("verify", "".join("- {}: {}\n".format(u["what"], u["why"]) for u in pending))
        fixed = {u["what"] for u in pending}
        # what the fix's review added stays
        e.unchecked = [u for u in e.unchecked[:before] if u["what"] not in fixed] + e.unchecked[before:]
        left = [u for u in e.unchecked if u["kind"] in UNCHECKED_KINDS]
        if done != "accept":
            left += [dict(u, why="found wrong: {}; the fix round did not pass".format(u["why"])) for u in pending]
        return e.routing.route_left(left)
