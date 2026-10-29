"""How a run ends: `Kind` (closed, no OTHER), `RunOutcome`, the one `POLICY` table and `apply`.

A run exit is a Kind. Everything the engine does at the close (bead status, label, ask or not, the loop's result, the
trace value, the storm count) is a cell of POLICY[kind]; a new reason is one enum member, one row and the raise site.
Machine faults (FAULT_*) never make an ask; network and killed stops (PAUSE_*) are paused, not failed, and count toward
no cap. `apply` is pure: the same (outcome, bead, history, now) gives the same Disposition. Stdlib only;
imports lifecycle (the one fingerprint normaliser), never engine.

Design: 60-design-A1 sec 2.1 and 61-integration sec 1.2; ASK_VERIFY is retired (68-design-asks sec 8); OWNER_PARK
is the owner's park (dash v2 backend item 7), so 23 members.
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from taskloop.domain.report import matchers as lifecycle


class Kind(enum.Enum):
    LANDED = "landed"
    DONE = "done"
    CUT = "cut"  # trial cell cut short; no production code raises it
    ASK_DECISION = "ask_decision"
    ASK_STUCK = "ask_stuck"
    ASK_BUDGET = "ask_budget"
    ASK_TICKET = "ask_ticket"
    WAIT_ASK = "wait_ask"  # an ask is still open: nothing new is asked or said
    PAUSE_LANE = "pause_lane"
    PAUSE_NETWORK = "pause_network"
    PAUSE_KILLED = "pause_killed"
    OWNER_PARK = "owner_park"  # the owner parked it (a park request): the branch and checkpoint stay, the hold keeps the loop off
    FAULT_INFRA = "fault_infra"
    FAULT_SLOT = "fault_slot"
    FAULT_DENIED = "fault_denied"
    FAULT_STALE_BASE = "fault_stale_base"
    FAULT_PLAN = "fault_plan"
    FAULT_LAND = "fault_land"
    FAULT_ENGINE = "fault_engine"
    FAULT_BAD_REQUEST = "fault_bad_request"
    FAULT_CONTRACT_SKEW = "fault_contract_skew"
    FAULT_BASE_RED = "fault_base_red"
    FAULT_CRASHED = "fault_crashed"


FINISH = (Kind.LANDED, Kind.DONE)
ASKS = tuple(k for k in Kind if k.name.startswith("ASK_"))
PAUSES = tuple(k for k in Kind if k.name.startswith("PAUSE_"))
FAULTS = tuple(k for k in Kind if k.name.startswith("FAULT_"))

# The tunables, in one place. Cells are values: a predicate goes to code.
KNOBS: Final = {
    "storm_window_s": 1800,      # the same fingerprint on storm_beads distinct beads inside this window trips the storm
    "storm_beads": 2,
    "fault_retries": 3,          # the same fingerprint on one bead this often escalates to one ASK_STUCK
    "fault_cooldown_s": 1800,    # a faulted bead is not picked again for this long (read by the loop when it takes over)
    "comment_dedupe_s": 3600,    # one engine comment per (bead, kind, fingerprint) per this long
    "loop_absent_s": 600,        # ready beads, no live loop and no beat for this long: the loop is absent
}


@dataclass(frozen=True)
class Rule:
    bd: str                 # close | open | block | none ("none": the bead stays as the ask left it)
    loop: str               # the loop's result: landed | failed | paused | parked
    trace: str              # the trace/ledger value: paused and parked are distinct
    makes_ask: bool
    resolver: str           # who clears it: none | clock | lane | network | engineer | owner | bead_author
    label: str = ""         # bd label added when the bead is left open
    storm: bool = False     # feeds the storm detector
    retries: int = 0        # same fingerprint on one bead before escalation (0: never escalates)
    escalate_to: "Kind | None" = None
    replan: bool = False    # the exit charges the replan cap
    wake: str = ""          # when a bead may be picked again: "" now | answer | lane | net | spec | cooldown


def _fault(resolver: str = "engineer") -> Rule:
    return Rule("open", "failed", "failed", False, resolver, label="engine-fault", storm=True,
                retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK, wake="cooldown")


def _ask(wake: str = "answer", replan: bool = False) -> Rule:
    return Rule("block", "parked", "parked", True, "owner", wake=wake, replan=replan)


POLICY: Final = {
    Kind.LANDED: Rule("close", "landed", "landed", False, "none"),
    Kind.DONE: Rule("close", "landed", "done", False, "none"),
    Kind.CUT: Rule("none", "paused", "paused", False, "none"),
    Kind.ASK_DECISION: _ask(),
    Kind.ASK_STUCK: _ask(replan=True),
    Kind.ASK_BUDGET: _ask(),
    Kind.ASK_TICKET: Rule("block", "parked", "parked", True, "bead_author", wake="spec"),
    Kind.WAIT_ASK: Rule("none", "parked", "parked", False, "owner", wake="answer"),
    Kind.PAUSE_LANE: Rule("open", "paused", "paused", False, "lane", wake="lane"),
    Kind.PAUSE_NETWORK: Rule("open", "paused", "paused", False, "network", wake="net"),  # counts toward no cap
    Kind.PAUSE_KILLED: Rule("open", "paused", "paused", False, "none"),
    Kind.OWNER_PARK: Rule("open", "parked", "parked", False, "owner"),
    Kind.FAULT_INFRA: _fault(),
    Kind.FAULT_SLOT: _fault(),
    Kind.FAULT_DENIED: _fault(),
    Kind.FAULT_STALE_BASE: _fault(),
    Kind.FAULT_PLAN: Rule("open", "failed", "failed", False, "engineer", label="engine-fault", storm=True,
                          retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK, replan=True, wake="cooldown"),
    Kind.FAULT_LAND: _fault(),
    Kind.FAULT_ENGINE: _fault(),
    Kind.FAULT_BAD_REQUEST: _fault(),
    Kind.FAULT_CONTRACT_SKEW: _fault(),
    Kind.FAULT_BASE_RED: _fault(),
    Kind.FAULT_CRASHED: _fault(),
}

ASK_NAME: Final = {Kind.ASK_DECISION: "decision", Kind.ASK_STUCK: "stuck", Kind.ASK_BUDGET: "budget", Kind.ASK_TICKET: "ticket"}


@dataclass(frozen=True)
class RunOutcome:
    kind: Kind
    fingerprint: str   # kind + the text with ids, numbers, paths and hex stripped; "" for LANDED and DONE
    detail: str        # human text; NEVER parsed by any module
    v: int = 1

    @property
    def rule(self) -> Rule:
        return POLICY[self.kind]


def fingerprint(kind: Kind, text: object) -> str:
    """The one normaliser: the kind name plus lifecycle's stripped text. Empty for a finish."""
    if kind in FINISH:
        return ""
    slug = lifecycle.fingerprint_head(text)
    return "{} {}".format(kind.name, slug or "unknown")


def make(kind: Kind, text: str = "") -> RunOutcome:
    return RunOutcome(kind, fingerprint(kind, text), text)


def load(kind: str, fp: str = "", detail: str = "", v: int = 1) -> RunOutcome:
    """A stored outcome. An unknown kind string or a newer version loads as FAULT_ENGINE with the raw text in detail:
    a reader never raises."""
    try:
        if v > 1:
            raise ValueError(v)
        return RunOutcome(Kind(kind), fp, detail, v)
    except ValueError:
        raw = f"{kind} {detail}"
        return RunOutcome(Kind.FAULT_ENGINE, fingerprint(Kind.FAULT_ENGINE, raw), raw)


@dataclass(frozen=True)
class Disposition:
    kind: Kind          # after escalation
    bd: str
    label: str
    loop_result: str
    trace_outcome: str
    ask: bool           # an owner ask is raised for this close
    comment: bool       # False: the same (bead, kind, fingerprint) was said within comment_dedupe_s
    escalated: bool     # a FAULT that hit its retries and became ASK_STUCK


def apply(outcome: RunOutcome, bead: str, history: Sequence[Mapping[str, Any]], now: float,
          knobs: Mapping[str, float] = KNOBS) -> Disposition:
    """The close's Disposition. history: earlier closes as dicts {bead, kind, fingerprint, t}, oldest first (any bead).
    Pure: no clock, no IO."""
    kind, rule = outcome.kind, outcome.rule
    escalated = False
    if rule.escalate_to and outcome.fingerprint:
        same = 1
        for h in reversed([h for h in history if h.get("bead") == bead]):
            if str(h.get("kind", "")).startswith("ask_"):
                break  # an ask ended the run of identical faults
            if h.get("fingerprint") == outcome.fingerprint:
                same += 1
        if same >= rule.retries:
            kind, rule, escalated = rule.escalate_to, POLICY[rule.escalate_to], True
    cut = now - knobs["comment_dedupe_s"]
    said = any(h.get("bead") == bead and h.get("kind") == kind.value and h.get("fingerprint") == outcome.fingerprint
               and float(h.get("t") or 0) >= cut for h in history)
    return Disposition(kind, rule.bd, rule.label, rule.loop, rule.trace, rule.makes_ask, not said, escalated)
