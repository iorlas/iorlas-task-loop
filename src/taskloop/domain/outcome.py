"""How a run ends: `Kind` (closed, no OTHER), `RunOutcome`, the one `POLICY` table and `apply`.

A run exit is a Kind. Everything the engine does at the close (bead status, label, ask or not, the loop's result, the
trace value, the storm count) is a cell of POLICY[kind]; a new reason is one enum member, one row and the raise site.
Machine faults (FAULT_*) never make an ask; network and killed stops (PAUSE_*) are paused, not failed, and count toward
no cap. `apply` is pure: the same (outcome, bead, history, now) gives the same Disposition. Stdlib only;
imports lifecycle (the one fingerprint normaliser), never engine.

Design: 60-design-A1 sec 2.1 and 61-integration sec 1.2; ASK_VERIFY is retired (68-design-asks sec 8); OWNER_PARK
is the owner's park (the dashboard's park verb), so 23 members.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from taskloop.contracts.enums import Outcome, Result
from taskloop.contracts.kinds import (
    ASK_NAME,
    ASKS,
    FAULTS,
    FINISH,
    PAUSES,
    Action,
    Fault,
    Infra,
    Kind,
    Owner,
    Task,
    action_of,
    fault_of,
    kind_named,
)
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.report import matchers as lifecycle

# the sealed set lives in contracts.kinds; callers reach it here
__all__ = [
    "ASKS", "ASK_NAME", "FAULTS", "FINISH", "PAUSES", "Action", "Fault", "Infra", "Kind", "Owner", "Task", "action_of", "fault_of",
    "kind_named",
]

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
    loop: Result            # the loop's result
    trace: str              # the trace/ledger value: paused and parked are distinct
    makes_ask: bool
    resolver: str           # who clears it: none | clock | lane | network | engineer | owner | bead_author
    label: str = ""         # bd label added when the bead is left open
    storm: bool = False     # feeds the storm detector
    retries: int = 0        # same fingerprint on one bead before escalation (0: never escalates)
    escalate_to: Kind | None = None
    replan: bool = False    # the exit charges the replan cap
    wake: str = ""          # when a bead may be picked again: "" now | answer | lane | net | spec | cooldown


def _fault(resolver: str = "engineer") -> Rule:
    return Rule("open", Result.FAILED, "failed", False, resolver, label="engine-fault", storm=True,
                retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK, wake="cooldown")


def _ask(wake: str = "answer", replan: bool = False) -> Rule:
    return Rule("block", Result.PARKED, "parked", True, "owner", wake=wake, replan=replan)


POLICY: Final = {
    Kind.LANDED: Rule("close", Result.LANDED, "landed", False, "none"),
    Kind.DONE: Rule("close", Result.LANDED, "done", False, "none"),
    Kind.CUT: Rule("none", Result.PAUSED, "paused", False, "none"),
    Kind.ASK_DECISION: _ask(),
    Kind.ASK_STUCK: _ask(replan=True),
    Kind.ASK_BUDGET: _ask(),
    Kind.ASK_TICKET: Rule("block", Result.PARKED, "parked", True, "bead_author", wake="spec"),
    Kind.WAIT_ASK: Rule("none", Result.PARKED, "parked", False, "owner", wake="answer"),
    Kind.PAUSE_LANE: Rule("open", Result.PAUSED, "paused", False, "lane", wake="lane"),
    Kind.PAUSE_NETWORK: Rule("open", Result.PAUSED, "paused", False, "network", wake="net"),  # counts toward no cap
    Kind.PAUSE_KILLED: Rule("open", Result.PAUSED, "paused", False, "none"),
    Kind.OWNER_PARK: Rule("open", Result.PARKED, "parked", False, "owner"),
    Kind.FAULT_INFRA: _fault(),
    Kind.FAULT_SLOT: _fault(),
    Kind.FAULT_DENIED: _fault(),
    Kind.FAULT_STALE_BASE: _fault(),
    Kind.FAULT_PLAN: Rule("open", Result.FAILED, "failed", False, "engineer", label="engine-fault", storm=True,
                          retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK, replan=True, wake="cooldown"),
    Kind.FAULT_LAND: _fault(),
    Kind.FAULT_ENGINE: _fault(),
    Kind.FAULT_BAD_REQUEST: _fault(),
    Kind.FAULT_CONTRACT_SKEW: _fault(),
    Kind.FAULT_BASE_RED: _fault(),
    Kind.FAULT_CRASHED: _fault(),
}



@dataclass(frozen=True)
class RunOutcome:
    """How one run ended: the kind decides everything (word, fault, policy); an ask carries its spec, nothing else does."""
    kind: Kind
    fingerprint: str   # kind + the text with ids, numbers, paths and hex stripped; "" for LANDED and DONE
    detail: str        # human text; NEVER parsed by any module
    v: int = 1
    sha: str = ""      # the land commit of a LANDED run
    spec: AskSpec | None = None

    def __post_init__(self) -> None:
        if (self.kind in ASKS) != (self.spec is not None):
            raise ValueError(f"{self.kind.name}: an ask carries a spec and nothing else does")

    @property
    def rule(self) -> Rule:
        return POLICY[self.kind]

    @property
    def fault(self) -> Fault | None:
        return fault_of(self.kind)

    @property
    def word(self) -> Outcome:
        """The trace's word: landed, done, failed (a fault, or a stop: the reports count it) or blocked (an ask, a pause, a wait)."""
        if self.kind is Kind.LANDED:
            return Outcome.LANDED
        if self.kind is Kind.DONE:
            return Outcome.DONE
        failed = POLICY[self.kind].loop is Result.FAILED or self.kind is Kind.PAUSE_KILLED
        return Outcome.FAILED if failed else Outcome.BLOCKED

    @property
    def finished(self) -> bool:
        return self.kind in FINISH


def fingerprint(kind: Kind, text: object) -> str:
    """The one normaliser: the kind name plus lifecycle's stripped text. Empty for a finish."""
    if kind in FINISH:
        return ""
    slug = lifecycle.fingerprint_head(text)
    return "{} {}".format(kind.name, slug or "unknown")


def make(kind: Kind, text: str = "", *, sha: str = "", spec: AskSpec | None = None) -> RunOutcome:
    return RunOutcome(kind, fingerprint(kind, text), text, sha=sha, spec=spec)


def load(kind: str, fp: str = "", detail: str = "", v: int = 1) -> RunOutcome:
    """A stored outcome. An unknown kind or another version is a ValueError: nothing reads a record as something it is not.
    A stored ask has no spec here (the ask itself is its own record), so it loads as its detail only when it is no ask."""
    if v != 1:
        raise ValueError(f"run outcome v={v!r}, this code reads v=1")
    k = Kind(kind)  # ValueError on an unknown kind
    if k in ASKS:
        raise ValueError(f"{k.value}: an ask is stored as an Ask, not as a RunOutcome")
    return RunOutcome(k, fp, detail, v)


@dataclass(frozen=True)
class Disposition:
    kind: Kind          # after escalation
    bd: str
    label: str
    loop_result: Result
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
