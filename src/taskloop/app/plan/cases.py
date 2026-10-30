"""The plan's cases and risks as the engine uses them: the checks that prove them, the text the workers read, what a review's
unchecked items mean against them, and the repo's worker rules."""
import json
from pathlib import Path
from typing import Any

from taskloop.contracts import plancheck
from taskloop.contracts.plancheck import PlanCheck
from taskloop.domain.checks import planref
from taskloop.domain.plan.matchers import evidence_files, word_set
from taskloop.domain.plan.stored import role_view
from taskloop.domain.prompts.common import RULES_MAX


class Cases:
    def __init__(self, host: Any) -> None:
        self.e = host

    def add_cases(self, new: Any):
        """A writer may add the cases it discovers; it can never remove one (the plan is the engine's)."""
        e = self.e
        cases = e.plan_data.setdefault("cases", [])
        have = {c["check"] for c in cases if c.get("check")}
        for c in new:
            why = planref.refusal(c["check"], e.cfg)
            if why:
                e.warn(f"the writer's case is not added: {why}")
            elif c["check"] not in have:
                cases.append(dict(c, by="writer"))
                have.add(c["check"])
                e.log.note("the writer added a case: {}".format(c["criterion"][:200]))

    def engine_unproven(self, unchecked: Any, checks: Any):
        """The unchecked items the engine does not prove itself: one that names the gate (it runs at land, and a red gate
        goes to a fix round) or a check that passed this round is dropped, and so is every case item once this round ran
        all the plan's cases green (only the last stage and a fix run them). lifesim-5ban.3 and lifesim-fld.27.3 stopped
        on verify asks for the gate; lifesim-gfr.31.1 on 'there is no nographics.out in evidence yet' after the case
        that writes it passed."""
        e = self.e
        ran = [c.cmd for c in checks if c.exit == 0]
        names = [" ".join(x.split()).lower() for x in [e.cfg.gate_text, *ran] if x.strip()]
        cases = planref.commands(self.case_checks(), e.cfg)
        cases_ran = bool(cases) and all(c in ran for c in cases)
        out = []
        for u in unchecked:
            what = " ".join(u["what"].split()).lower()
            if any(x in what for x in names) or (cases_ran and u["kind"] == "case"):
                e.log.note("unchecked item dropped, the engine runs it: {}".format(u["what"][:200]))
            else:
                out.append(u)
        return out

    def scope_tokens(self):
        e = self.e
        plan = e.plan_data or {}
        text = [e.scope] + [st["goal"] for st in plan.get("stages") or []] + [
            c["criterion"] for c in plan.get("cases") or []] + [r["what"] for r in plan.get("risks") or []]
        return word_set(" ".join(text))

    def out_of_scope(self, items: Any):
        """tl-bxk.13.5: a checkable item a review noted that shares nothing with the bead's done-when, the plan's goals, cases
        and risks is a follow-up, not a gap: it is filed as a leftover and the land goes on (lifesim-f2by: a note about two
        poses nobody asked for became two fix rounds, 93 min). Nothing is dropped unseen: the bead is filed. With no
        acceptance text to compare against, nothing moves."""
        e = self.e
        if not e.scope.strip():
            return items
        have = self.scope_tokens()
        keep: list[Any] = []
        for u in items:
            toks = word_set(u["what"])
            near = len(toks & have)
            if u["kind"] != "checkable" or near >= 2 or (toks and near / len(toks) >= 0.3):
                keep.append(u)
                continue
            e.log.note("unchecked item outside the done-when, filed as a follow-up: {}".format(u["what"][:200]))
            title = ("Check: " + u["what"])[:120]
            if title in {lo["title"] for lo in e.leftovers}:
                continue
            e.leftovers.append({"title": title, "why": "A review noted this outside the task's "
                                   "done-when, so it was not verified before the land: " + u["what"][:600]})
        return keep

    def case_checks(self) -> list[PlanCheck]:
        e = self.e
        return [c["check"] for c in (e.plan_data or {}).get("cases") or []
                if c.get("check") and c.get("class", "test") == "test" and c.get("proved_by", "check") in ("check", "stage")]

    def cases_of(self, cls: Any):
        """The criteria of the plan's cases of one class (look-objective, taste)."""
        e = self.e
        return [c["criterion"] for c in (e.plan_data or {}).get("cases") or [] if c.get("class") == cls]

    def cases_text(self) -> str:
        cases = (self.e.plan_data or {}).get("cases") or []
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
        e = self.e
        rel = e.cfg.worker_rules
        if not rel:
            return ""
        try:
            text = (Path(e.wt) / rel).read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return ""
        if len(text.encode("utf-8")) > RULES_MAX:
            e.warn(f"worker rules {rel} are over {RULES_MAX} bytes: only the first lines that fit are sent")
            text = text.encode("utf-8")[:RULES_MAX].decode("utf-8", "ignore").rsplit("\n", 1)[0].rstrip()
        return text

    def plan_text(self, stage: Any = None):
        """The plan as JSON; with `stage` (0-based) the role-sized view a writer or reviewer of that stage reads."""
        e = self.e
        plan = e.plan_data or {}
        return json.dumps(plancheck.to_wire(plan if stage is None else role_view(plan, stage)), indent=1)

    def promised_missing(self, plan: Any, upto: int) -> int | None:
        """tl-bxk.13.16.2: the index of the earliest accepted stage (before `upto`) that mentions an evidence file which is gone
        now while a check still to run names it, or None."""
        e = self.e
        stages = plan.get("stages") or []
        pending = [plancheck.text_of(c) for st in stages[upto:] for c in st["checks"]] + [
            plancheck.text_of(x["check"]) for x in plan.get("cases") or [] if x.get("check") and x.get("class", "test") == "test"]
        need = {p for c in pending for p in evidence_files(e.bead, c) if not Path(e.wt, p).exists()}
        early = [k for k, st in enumerate(stages[:upto])
                 if any(p in plancheck.text_of(c) for c in st["checks"] for p in need)]
        return min(early) if early else None
