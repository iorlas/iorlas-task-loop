"""The plan's cases and risks as the engine uses them: the checks that prove them, the text the workers read, what a review's
unchecked items mean against them, and the repo's worker rules."""
import json
from collections.abc import Sequence
from pathlib import Path

from tlkernel import plancheck
from tlkernel.checks import CheckResult
from tlkernel.plancheck import PlanCheck, PlanData
from tlkernel.stagefacts import RunFacts
from tlkernel.wire import Open

from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.host import PlanHand, PlanPorts
from taskloop.app.plan.state import PlanState
from taskloop.domain.checks import planref
from taskloop.domain.plan.matchers import evidence_files, word_set
from taskloop.domain.plan.stored import role_view
from taskloop.domain.prompts.common import RULES_MAX


class Cases:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand

    def add_cases(self, new: Sequence[Open]) -> None:
        """A writer may add the cases it discovers; it can never remove one (the plan is the engine's)."""
        assert self.hand.plan_data is not None, "cases are added to a plan that exists"
        cases = self.hand.plan_data.setdefault("cases", [])
        have = {c["check"] for c in cases if c.get("check")}
        for c in new:
            why = planref.refusal(c["check"], self.facts.cfg)
            if why:
                self.ports.warn(f"the writer's case is not added: {why}")
            elif c["check"] not in have:
                cases.append(dict(c, by="writer"))
                have.add(c["check"])
                self.ports.log.note("the writer added a case: {}".format(c["criterion"][:200]))

    def engine_unproven(self, unchecked: list[Open], checks: Sequence[CheckResult]) -> list[Open]:
        """The unchecked items the engine does not prove itself: one that names the gate (it runs at land, and a red gate
        goes to a fix round) or a check that passed this round is dropped, and so is every case item once this round ran
        all the plan's cases green (only the last stage and a fix run them). two consumer beads stopped
        on verify asks for the gate; a third on 'there is no nographics.out in evidence yet' after the case
        that writes it passed."""
        ran = [c.cmd for c in checks if c.exit == 0]
        names = [" ".join(x.split()).lower() for x in [self.facts.cfg.gate_text, *ran] if x.strip()]
        cases = planref.commands(self.case_checks(), self.facts.cfg)
        cases_ran = bool(cases) and all(c in ran for c in cases)
        out = []
        for u in unchecked:
            what = " ".join(u["what"].split()).lower()
            if any(x in what for x in names) or (cases_ran and u["kind"] == "case"):
                self.ports.log.note("unchecked item dropped, the engine runs it: {}".format(u["what"][:200]))
            else:
                out.append(u)
        return out

    def scope_tokens(self):
        plan = self.hand.plan_data or {}
        text = [self.hand.scope] + [st["goal"] for st in plan.get("stages") or []] + [
            c["criterion"] for c in plan.get("cases") or []] + [r["what"] for r in plan.get("risks") or []]
        return word_set(" ".join(text))

    def out_of_scope(self, items: list[Open]) -> list[Open]:
        """tl-bxk.13.5: a checkable item a review noted that shares nothing with the bead's done-when, the plan's goals, cases
        and risks is a follow-up, not a gap: it is filed as a leftover and the land goes on (a consumer run: a note about two
        poses nobody asked for became two fix rounds, 93 min). Nothing is dropped unseen: the bead is filed. With no
        acceptance text to compare against, nothing moves."""
        if not self.hand.scope.strip():
            return items
        have = self.scope_tokens()
        keep: list[Open] = []
        for u in items:
            toks = word_set(u["what"])
            near = len(toks & have)
            if u["kind"] != "checkable" or near >= 2 or (toks and near / len(toks) >= 0.3):
                keep.append(u)
                continue
            self.ports.log.note("unchecked item outside the done-when, filed as a follow-up: {}".format(u["what"][:200]))
            title = ("Check: " + u["what"])[:120]
            if not self.ports.leftover_sink.add_titled({"title": title, "why": "A review noted this outside the task's "
                                   "done-when, so it was not verified before the land: " + u["what"][:600]}):
                continue
            self.ports.checkpoints.keep_pending("scope")
        return keep

    def case_checks(self) -> list[PlanCheck]:
        return [c["check"] for c in (self.hand.plan_data or {}).get("cases") or []
                if c.get("check") and c.get("class", "test") == "test" and c.get("proved_by", "check") in ("check", "stage")]

    def cases_of(self, cls: str) -> list[str]:
        """The criteria of the plan's cases of one class (look-objective, taste)."""
        return [c["criterion"] for c in (self.hand.plan_data or {}).get("cases") or [] if c.get("class") == cls]

    def cases_text(self) -> str:
        cases = (self.hand.plan_data or {}).get("cases") or []
        run = [c for c in cases if c.get("class", "test") == "test"]
        looked = [c for c in cases if c.get("class", "test") != "test"]
        text = ""
        if run:
            text += "\nThe task's acceptance cases (they run on the last stage; judge whether each proves its criterion):\n"
            for c in run:
                by = (f" (added by the writer: {c.get('why', '')}; check it does not replace a stronger case)"
                      if c.get("by") == "writer" else "")
                text += f"- {c['criterion']}: `{plancheck.shown(c['check'])}`{by}\n"
        if looked:
            text += ("\nCases judged from rendered pictures, not by a command (the engine's look judge sees them; taste goes to the "
                     "owner):\n")
            text += "".join(f"- [{c['class']}] {c['criterion']}\n" for c in looked)
        return text

    def rules_text(self):
        """tl-7y6.6.1: the repo's worker rules (engine.worker_rules), inlined; "" when none. A file over RULES_MAX is cut at a line
        and the engine warns: the limit is hard, so the planner and the writer share one text and nobody reads a path."""
        rel = self.facts.cfg.worker_rules
        if not rel:
            return ""
        try:
            text = (Path(self.facts.wt) / rel).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""
        if len(text.encode("utf-8")) > RULES_MAX:
            self.ports.warn(f"worker rules {rel} are over {RULES_MAX} bytes: only the first lines that fit are sent")
            text = text.encode("utf-8")[:RULES_MAX].decode("utf-8", "ignore").rsplit("\n", 1)[0].rstrip()
        return text

    def plan_text(self, stage: int | None = None) -> str:
        """The plan as JSON; with `stage` (0-based) the role-sized view a writer or reviewer of that stage reads."""
        plan = self.hand.plan_data or {}
        return json.dumps(plancheck.to_wire(plan if stage is None else role_view(plan, stage)), indent=1)

    def promised_missing(self, plan: PlanData, upto: int) -> int | None:
        """tl-bxk.13.16.2: the index of the earliest accepted stage (before `upto`) that mentions an evidence file which is gone
        now while a check still to run names it, or None."""
        stages = plan.get("stages") or []
        pending = [plancheck.text_of(c) for st in stages[upto:] for c in st["checks"]] + [
            plancheck.text_of(x["check"]) for x in plan.get("cases") or [] if x.get("check") and x.get("class", "test") == "test"]
        need = {p for c in pending for p in evidence_files(self.facts.bead, c) if not Path(self.facts.wt, p).exists()}
        early = [k for k, st in enumerate(stages[:upto])
                 if any(p in plancheck.text_of(c) for c in st["checks"] for p in need)]
        return min(early) if early else None
