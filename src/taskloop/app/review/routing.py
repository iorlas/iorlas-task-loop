"""Routing: where an unchecked item goes once the engine knows what it is (tl-bxk.10.28). An engine step is settled, a checkable item
goes to the writer for a test, an item no check can prove lands unverified for the owner, an owner decision is asked. The ledger of the
plan (what it defers, what it leaves to the engine) is read before the item's kind."""
from typing import Any

from taskloop.contracts.plancheck import PlanData
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.plan.matchers import word_set
from taskloop.domain.review import kinds
from taskloop.domain.review.ledger import Ledger
from taskloop.domain.review.matchers import Wording

Item = dict[str, Any]
AT_LAND = "the engine does this at land"


class Routing:
    def __init__(self, host: Any) -> None:
        self.e = host

    def ledger(self) -> Ledger:
        return Ledger(self.e.plan_data, self.e.leftovers)

    def ledger_of(self, plan: PlanData) -> Ledger:
        """The ledger of a plan not yet accepted (the engine's leftovers count as deferred)."""
        return Ledger(plan, self.e.leftovers)

    def ledger_route(self, what: str) -> str:
        return self.ledger().route(what)

    def has_leftovers(self) -> bool:
        return bool(self.e.leftovers or (self.e.plan_data or {}).get("leftovers"))

    def engine_does(self, what: str) -> bool:
        return kinds.engine_does(what, self.has_leftovers())

    def names_code(self, what: str) -> bool:
        e = self.e
        files = set(e.git("ls-files").splitlines()) | set(e.checkout.changed_paths())
        return kinds.names_code(what, files, {f.rsplit("/", 1)[-1] for f in files}, e.diff_text)

    def resolve_kind(self, u: Item, a: Item) -> tuple[str, str]:
        """(kind, source) for an item, by kinds.resolve_kind."""
        source = (a.get("source") or u.get("source") or "").strip()
        return kinds.resolve_kind(u["kind"], a.get("kind"), source, lambda: self.engine_does(u["what"]),
                                  lambda: self.names_code(u["what"])), source

    def settle_engine_step(self, u: Item) -> None:
        self.e.verified.append({"what": u["what"], "kind": u["kind"], "verdict": "settled", "why": AT_LAND, "evidence": AT_LAND})

    def add_unverified(self, u: Item, why: str) -> None:
        if u["what"] not in {x["what"] for x in self.e.unverified}:
            self.e.unverified.append({"what": u["what"], "kind": u["kind"], "why": why, "source": u.get("source") or ""})

    def backed_by_leftover(self, what: str) -> bool:
        """True when an owner-review follow-up bead for this item is already in the leftovers (tl-bxk.13.1): the owner sees it there, so
        it need not stop the land as well (lifesim-iqad twice)."""
        mine = word_set(what)
        if len(mine) < 3:
            return False
        for lo in self.e.leftovers:  # the beads the engine will file
            t, w = " ".join(str(lo.get("title") or "").split()), str(lo.get("why") or "")
            if Wording.ownerish(t) and len(mine & word_set(t + " " + w)) >= max(4, int(0.5 * len(mine))):
                return True
        return False

    def engine_steps(self, gaps: list[Item]) -> list[Item]:
        """tl-bxk.10.28: an item the writer calls an engine step is settled here, no verifier call, only when it names an action the
        engine will do for this bead (engine_does). A claim about the result ('the beads cover all nine objects') goes to the verifier."""
        out: list[Item] = []
        for u in gaps:
            route = self.ledger_route(u["what"])
            if (u["kind"] == "engine_step" and self.engine_does(u["what"])) or route == "engine_step":
                self.settle_engine_step(u)
            elif route == "leftover":
                self.add_unverified(u, "the plan defers it to a follow-up bead")
            elif u["kind"] in ("owner_decision", "external_fact", "taste") and self.backed_by_leftover(u["what"]):
                self.add_unverified(u, "a follow-up bead for the owner is filed at land")
            elif u["kind"] in ("engine_step", "external_fact", "taste"):
                out.append(dict(u, kind=self.resolve_kind(u, {"kind": u["kind"], "source": "x"})[0]))  # source is the verifier's to give
            else:
                out.append(u)
        return out

    def proof_stuck(self, items: list[Item]) -> Any:
        cap = int(self.e.cfg.max_fix_rounds)
        what = [u["what"] for u in items]
        why = f"the check before land: nothing proves {'; '.join(what)[:600]} after {cap} fix rounds: it needs the owner's hint"
        return self.e.blocked_for(why, "ASK_STUCK", spec=askspecs.unproven(what, cap))

    def route_open(self, u: Item, a: Item, why: str) -> tuple[str, Item, str, str]:
        """Where an item the verifier left open goes, by its (resolved) kind: (verdict, answer, why, route). An engine step is settled; a
        checkable item goes to the writer for a test (a fix round, counted in max_fix_rounds; none left: the bead is stuck, never
        landed); an item no check can prove lands for the owner (route 'unverified'); an owner decision, or an old kind, is asked."""
        k, route = u["kind"], self.ledger_route(u["what"])
        if route == "leftover":
            self.add_unverified(u, why or "the plan defers it to a follow-up bead")
            return "open", a, why, "unverified"
        if k == "engine_step" or route == "engine_step":
            return "settled", dict(a, evidence=AT_LAND), AT_LAND, ""
        if k == "checkable":
            if self.e.fixes >= int(self.e.cfg.max_fix_rounds):
                raise self.proof_stuck([u])
            return "wrong", a, "add a test or check that proves: {}".format(u["what"]), "proof"
        if k in ("external_fact", "taste"):
            self.add_unverified(u, why)
            return "open", a, why, "unverified"
        return "open", a, why, ""

    def route_left(self, left: list[Item]) -> list[Item]:
        """The items still unchecked after a verify fix round, routed: an engine step the engine does is settled; one that no check can
        prove (external_fact with a source, taste) lands unverified; a checkable one (or one a failed proving round left) comes back
        flagged proof_round, to be sent again while a fix round is left; the rest still asks."""
        out: list[Item] = []
        for u in left:
            defect = str(u.get("why") or "").startswith("found wrong:") and not u.get("proof_round")
            route = "" if defect else self.ledger_route(u["what"])  # a defect the verifier found is never the ledger's
            if route == "engine_step":
                self.settle_engine_step(u)
            elif route == "leftover":
                self.add_unverified(dict(u, kind=u.get("kind") or "other"), "the plan defers it to a follow-up bead")
            else:
                self.route_one(u, defect, out)
        return out

    def route_one(self, u: Item, defect: bool, out: list[Item]) -> None:
        k = "checkable" if u.get("proof_round") else self.resolve_kind(u, {})[0]
        if defect:
            out.append(u)
        elif k == "engine_step":
            self.settle_engine_step(u)
        elif k in ("external_fact", "taste"):
            self.add_unverified(dict(u, kind=k), u.get("why") or "")
        elif k == "owner_decision" and self.backed_by_leftover(u["what"]):
            self.add_unverified(dict(u, kind=k), "a follow-up bead for the owner is filed at land")
        else:
            out.append(dict(u, kind=k, proof_round=True) if k == "checkable" else u)

