"""What is wrong with a planner's answer: its checks are validated before any write; the ones that read the tracker, run gate-only
commands or cannot run go back once, on the same planner thread, with the exact errors."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from tlgate.domain import lint, planref
from tlkernel import plancheck
from tlkernel.plancheck import PlanData
from tlkernel.stagefacts import RunFacts
from tlwork.prompts.anchors import MAX_ANCHORS, unanchored

from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.assume import assume
from taskloop.app.plan.host import PlanHand, PlanPorts
from taskloop.app.plan.prompts import (
    DRY_CHECK_TEXT,
    EMPTY_PLAN_TEXT,
    GATE_ONLY_ACCEPTANCE,
    GATE_ONLY_ACCEPTANCE_TEXT,
    REFUSED_CHECKS_TEXT,
    TRACKER_TEXT,
    UNANCHORED_TEXT,
)
from taskloop.app.plan.state import PlanState
from taskloop.domain.plan.matchers import gate_only_criteria


@dataclass
class Problems:
    empty: bool = False
    only: list[str] = field(default_factory=list)
    bad: list[str] = field(default_factory=list)
    gated: list[tuple[str, str]] = field(default_factory=list)
    dry: list[str] = field(default_factory=list)
    loose: list[str] = field(default_factory=list)  # "stage N: file" for an existing file with no anchor
    refused: list[str] = field(default_factory=list)  # a ref or a read of a check the repo lacks, a wrapper of a registered check

    def any(self) -> bool:
        return bool(self.empty or self.only or self.bad or self.gated or self.dry or self.loose or self.refused)

    def moved(self) -> str:
        parts = (["has no stages"] if self.empty else []) + (["checks read the issue tracker"] if self.bad else [])
        parts += [f"acceptance is only the gate ({GATE_ONLY_ACCEPTANCE})"] if self.only else []
        parts += (["checks run gate-only commands"] if self.gated else []) + (["existing files have no anchor"] if self.loose else [])
        parts += ["checks name or wrap registered checks wrongly"] if self.refused else []
        return "plan " + "; ".join(parts + (["checks cannot run"] if self.dry else []))


class SendBack:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand

    def find(self, data: PlanData) -> Problems:
        """The problems of a first answer."""
        dry = lint.dry_check(data, self.ports.shell_probe(), self.facts.cfg)
        dry += (lint.ledger_problems(data) + lint.own_timeout_problems(data, self.facts.cfg.check_wall_min)
                + lint.evidence_problems(data, str(self.facts.evidence_dir)))
        # tl-wjj: no stages, no question and nothing to file breaks the plan contract: back once. With leftovers it is the
        # finished-work plan (tl-bxk.13.2); with the owner's verify answer it may be empty.
        empty = (not data["stages"] and not data["question"].strip() and not data.get("leftovers") and not self.hand.leftovers
                 and not self.hand.verify_answer)
        return Problems(empty, gate_only_criteria(data, self.facts.cfg), lint.tracker_checks(data),
                        lint.gate_only_checks(data, self.facts.cfg), dry, self.loose(data),
                        planref.refusals(planref.plan_checks(data), self.facts.cfg))

    def loose(self, data: PlanData) -> list[str]:
        """Stages that change an existing file no anchor names; a stage with more than 8 anchors keeps the first 8."""
        out = list[str]()
        for n, st in enumerate(data["stages"], 1):
            st["anchors"] = (st.get("anchors") or [])[:MAX_ANCHORS]
            there = {f: Path(self.facts.wt, f).exists() for f in st["files"]}
            out += [f"stage {n}: {f}" for f in unanchored(st, there)]
        return out

    def text(self, p: Problems) -> str:
        """The warnings logged and the reasons the plan goes back with."""
        why = ""
        if p.empty:
            self.ports.warn("the plan has no stages, no question and nothing to file, sent back")
            why += EMPTY_PLAN_TEXT
        if p.loose:
            self.ports.warn("the plan names no anchor for existing files, sent back: " + "; ".join(p.loose)[:300])
            why += UNANCHORED_TEXT % "\n".join(f"- {x}" for x in p.loose)
        if p.only:
            self.ports.warn(f"the plan's acceptance is only the gate, sent back ({GATE_ONLY_ACCEPTANCE}): " + "; ".join(p.only)[:300])
            why += GATE_ONLY_ACCEPTANCE_TEXT % (GATE_ONLY_ACCEPTANCE, self.facts.cfg.gate_text or "the gate",
                                               "\n".join(f"- {c}" for c in p.only))
        if p.bad:
            self.ports.warn("the plan's checks read the issue tracker, sent back: " + "; ".join(p.bad)[:300])
            why += TRACKER_TEXT % "\n".join(f"- `{c}`" for c in p.bad)
        if p.gated:
            self.ports.warn("the plan's checks run gate-only commands, sent back: " + "; ".join(f"{c} ({w})" for c, w in p.gated)[:300])
            why += lint.GATE_ONLY_TEXT % "\n".join(f"- `{c}`: {w}" for c, w in p.gated)
        if p.refused:
            self.ports.warn("the plan's checks name or wrap registered checks wrongly, sent back: " + "; ".join(p.refused)[:300])
            why += REFUSED_CHECKS_TEXT % "\n".join("- " + r for r in p.refused)
        if p.dry:
            self.ports.warn("the plan's checks cannot run, sent back: " + "; ".join(p.dry)[:300])
            why += DRY_CHECK_TEXT % "\n".join("- " + d for d in p.dry)
        return why

    def rewrite(self, data: PlanData, prompt: str, step: str, why: str) -> PlanData:
        """Ask once more, on the same planner thread when there is one."""
        ref = self.hand.planner_ref
        wire = json.dumps(plancheck.to_wire(data), indent=1)
        back = (why.lstrip() + "\n\nYour plan, to correct (same output schema):\n" + wire) if ref else prompt + why
        return plancheck.plan_of(self.ports.ai("plan", "rewrite checks", back, step=step, mode="checks_back", delta=back if ref else None,
                                      at=(self.hand.planned, 1, 0)).data)

    def after_rewrite(self, data: PlanData) -> None:
        """What the rewrite still gets wrong: a stop, or (the heuristics) a warning; there is no second send-back."""
        only, bad = gate_only_criteria(data, self.facts.cfg), lint.tracker_checks(data)
        if only:
            raise self.ports.blocked_for(
                f"failed: the plan's acceptance is still only the gate after one rewrite ({GATE_ONLY_ACCEPTANCE}): "
                                + "; ".join(only)[:400], "FAULT_PLAN")
        if bad:
            raise self.ports.blocked_for(
                "failed: the plan's checks still read the issue tracker after one rewrite: " + "; ".join(bad)[:400],
                                "FAULT_PLAN")
        self.leave_to_gate(data)
        refused = planref.refusals(planref.plan_checks(data), self.facts.cfg)
        if refused:
            raise self.ports.blocked_for(
                "failed: the plan's checks still name or wrap registered checks wrongly after one rewrite: "
                                + "; ".join(refused)[:400], "FAULT_PLAN")
        dry = lint.dry_check(data, self.ports.shell_probe(), self.facts.cfg)
        paths = [why for why in dry if "CHECKPATH:" in why]
        if paths:
            raise self.ports.blocked_for(
                "failed: CHECKPATH: check executable paths are still invalid after one rewrite: "
                                + "; ".join(paths)[:400], "FAULT_PLAN")
        if dry:
            self.ports.warn("the plan's checks may still not run after one rewrite: " + "; ".join(dry)[:300])

    def leave_to_gate(self, data: PlanData) -> None:
        """Drop commands the rewrite left for stage checks but only the land gate may run; keep their stages and a visible note."""
        gated = dict(lint.gate_only_checks(data, self.facts.cfg))
        dropped = {c for c in lint.own_checks(data) if c.text in gated}
        for stage in data["stages"]:
            stage["checks"] = [c for c in stage["checks"] if c not in dropped]
        for risk in data.get("risks") or []:
            if risk.get("check") in dropped:
                risk["check"] = None
        for case in data.get("cases") or []:
            if case.get("check") in dropped:
                case.update(check=None, proved_by="engine_step", via="land gate")
        for cmd, why in gated.items():
            assume(data, f"Plan check `{cmd}` left to the gate: {why}", self.ports.log.note)
