"""What is wrong with a planner's answer: its checks are validated before any write; the ones that read the tracker, run gate-only
commands or cannot run go back once, on the same planner thread, with the exact errors."""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from taskloop.contracts.argv import checks_to_wire
from taskloop.domain.checks import lint
from taskloop.domain.plan.matchers import gate_only_criteria
from taskloop.domain.prompts.anchors import MAX_ANCHORS, unanchored
from taskloop.domain.prompts.plan import (
    DRY_CHECK_TEXT,
    EMPTY_PLAN_TEXT,
    GATE_ONLY_ACCEPTANCE,
    GATE_ONLY_ACCEPTANCE_TEXT,
    TRACKER_TEXT,
    UNANCHORED_TEXT,
)


@dataclass
class Problems:
    empty: bool = False
    only: list[str] = field(default_factory=list)
    bad: list[str] = field(default_factory=list)
    gated: list[tuple[str, str]] = field(default_factory=list)
    dry: list[str] = field(default_factory=list)
    loose: list[str] = field(default_factory=list)  # "stage N: file" for an existing file with no anchor

    def any(self) -> bool:
        return bool(self.empty or self.only or self.bad or self.gated or self.dry or self.loose)

    def moved(self) -> str:
        parts = (["has no stages"] if self.empty else []) + (["checks read the issue tracker"] if self.bad else [])
        parts += [f"acceptance is only the gate ({GATE_ONLY_ACCEPTANCE})"] if self.only else []
        parts += (["checks run gate-only commands"] if self.gated else []) + (["existing files have no anchor"] if self.loose else [])
        return "plan " + "; ".join(parts + (["checks cannot run"] if self.dry else []))


class SendBack:
    def __init__(self, host: Any) -> None:
        self.e = host

    def find(self, data: dict[str, Any]) -> Problems:
        """The problems of a first answer."""
        e = self.e
        dry = lint.dry_check(data, e.shell_probe())
        dry += (lint.ledger_problems(data) + lint.own_timeout_problems(data, e.cfg.check_wall_min) + lint.rerun_problems(data, e.cfg)
                + lint.producer_problems(data, e.cfg) + lint.evidence_problems(data, str(e.evidence_dir)))
        # tl-wjj: no stages, no question and nothing to file breaks the plan contract: back once. With leftovers it is the
        # finished-work plan (tl-bxk.13.2); with the owner's verify answer it may be empty.
        empty = (not data["stages"] and not data["question"].strip() and not data.get("leftovers") and not e.leftovers
                 and not e.verify_answer)
        return Problems(empty, gate_only_criteria(data, e.cfg), lint.tracker_checks(data),
                        lint.gate_only_checks(data, e.cfg), dry, self.loose(data))

    def loose(self, data: dict[str, Any]) -> list[str]:
        """Stages that change an existing file no anchor names; a stage with more than 8 anchors keeps the first 8."""
        e, out = self.e, list[str]()
        for n, st in enumerate(data["stages"], 1):
            st["anchors"] = (st.get("anchors") or [])[:MAX_ANCHORS]
            there = {f: Path(e.wt, f).exists() for f in st["files"]}
            out += [f"stage {n}: {f}" for f in unanchored(st, there)]
        return out

    def text(self, p: Problems) -> str:
        """The warnings logged and the reasons the plan goes back with."""
        e, why = self.e, ""
        if p.empty:
            e.warn("the plan has no stages, no question and nothing to file, sent back")
            why += EMPTY_PLAN_TEXT
        if p.loose:
            e.warn("the plan names no anchor for existing files, sent back: " + "; ".join(p.loose)[:300])
            why += UNANCHORED_TEXT % "\n".join(f"- {x}" for x in p.loose)
        if p.only:
            e.warn(f"the plan's acceptance is only the gate, sent back ({GATE_ONLY_ACCEPTANCE}): " + "; ".join(p.only)[:300])
            why += GATE_ONLY_ACCEPTANCE_TEXT % (GATE_ONLY_ACCEPTANCE, e.cfg.gate_text or "the gate", "\n".join(f"- {c}" for c in p.only))
        if p.bad:
            e.warn("the plan's checks read the issue tracker, sent back: " + "; ".join(p.bad)[:300])
            why += TRACKER_TEXT % "\n".join(f"- `{c}`" for c in p.bad)
        if p.gated:
            e.warn("the plan's checks run gate-only commands, sent back: " + "; ".join(f"{c} ({w})" for c, w in p.gated)[:300])
            why += lint.GATE_ONLY_TEXT % "\n".join(f"- `{c}`: {w}" for c, w in p.gated)
        if p.dry:
            e.warn("the plan's checks cannot run, sent back: " + "; ".join(p.dry)[:300])
            why += DRY_CHECK_TEXT % "\n".join("- " + d for d in p.dry)
        return why

    def rewrite(self, data: dict[str, Any], prompt: str, step: str, why: str) -> dict[str, Any]:
        """Ask once more, on the same planner thread when there is one."""
        e = self.e
        ref = e.planner_ref
        wire = json.dumps(checks_to_wire(data), indent=1)
        back = (why.lstrip() + "\n\nYour plan, to correct (same output schema):\n" + wire) if ref else prompt + why
        again, _ = e.ai("plan", "rewrite checks", back, step=step, mode="checks_back", resume_ref=ref or None, at=(e.planned, 1, 0))
        return again

    def after_rewrite(self, data: dict[str, Any]) -> None:
        """What the rewrite still gets wrong: a stop, or (the heuristics) a warning; there is no second send-back."""
        e = self.e
        only, bad, gated = gate_only_criteria(data, e.cfg), lint.tracker_checks(data), lint.gate_only_checks(data, e.cfg)
        if only:
            raise e.blocked_for(f"failed: the plan's acceptance is still only the gate after one rewrite ({GATE_ONLY_ACCEPTANCE}): "
                                + "; ".join(only)[:400], "FAULT_PLAN")
        if bad:
            raise e.blocked_for("failed: the plan's checks still read the issue tracker after one rewrite: " + "; ".join(bad)[:400],
                                "FAULT_PLAN")
        if gated:
            raise e.blocked_for("failed: the plan's checks still run gate-only commands after one rewrite: "
                                + "; ".join(f"{c} ({w})" for c, w in gated)[:400], "FAULT_PLAN")
        dry = lint.dry_check(data, e.shell_probe()) + lint.rerun_problems(data, e.cfg)
        if dry:
            e.warn("the plan's checks may still not run after one rewrite: " + "; ".join(dry)[:300])
