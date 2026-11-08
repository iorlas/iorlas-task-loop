"""How a run ends: `Kind` (closed, no OTHER), `RunOutcome`, the one `POLICY` table and `apply`.

A run exit is a Kind. Everything the engine does at the close (bead status, label, ask or not, the loop's result, the
trace value) is a cell of POLICY[kind]; a new reason is one enum member, one row and the raise site.
Machine faults (FAULT_*) never make an ask; network and killed stops (PAUSE_*) are paused, not failed, and count toward
no cap. `apply` is pure: the same (outcome, bead, history, now) gives the same Disposition. Stdlib only;
imports lifecycle (the one fingerprint normaliser), never engine.

Design: 60-design-A1 sec 2.1 and 61-integration sec 1.2; ASK_VERIFY is retired (68-design-asks sec 8); OWNER_PARK
is the owner's park (the dashboard's park verb), so 23 members.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from any_failure_fp import Event, seen_within, streak

from tlkernel import lifecyclematchers as lifecycle
from tlkernel.askspec import AskSpec
from tlkernel.enums import Outcome, Result
from tlkernel.kinds import (
    ASKS,
    FINISH,
    Fault,
    Kind,
    fault_of,
)
from tlkernel.reconcile import LOOP_ABSENT_S

# The tunables, in one place. Cells are values: a predicate goes to code.
KNOBS: Final = {
    "fault_retries": 3,          # the same fingerprint on one bead this often escalates to one ASK_STUCK
    "comment_dedupe_s": 3600,    # one engine comment per (bead, kind, fingerprint) per this long
    "loop_absent_s": LOOP_ABSENT_S,        # ready beads, no live loop and no beat for this long: the loop is absent
}


@dataclass(frozen=True)
class Rule:
    bd: str                 # close | open | block | none ("none": the bead stays as the ask left it)
    loop: Result            # the loop's result
    trace: str              # the trace/ledger value: paused and parked are distinct
    makes_ask: bool
    resolver: str           # who clears it: none | clock | account | network | engineer | owner | bead_author
    label: str = ""         # bd label added when the bead is left open
    retries: int = 0        # same fingerprint on one bead before escalation (0: never escalates)
    escalate_to: Kind | None = None
    replan: bool = False    # the exit charges the replan cap
    wake: str = ""          # when a bead may be picked again: "" now | answer | account | net | spec | cooldown


def _fault(resolver: str = "engineer") -> Rule:
    return Rule("open", Result.FAILED, "failed", False, resolver, label="engine-fault",
                retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK)


def _ask(wake: str = "answer", replan: bool = False) -> Rule:
    return Rule("block", Result.PARKED, "parked", True, "owner", wake=wake, replan=replan)


POLICY: Final = {
    Kind.LANDED: Rule("close", Result.LANDED, "landed", False, "none"),
    Kind.DONE: Rule("close", Result.LANDED, "done", False, "none"),
    Kind.STAGE: Rule("none", Result.STAGED, "staged", False, "none"),
    Kind.NOOP: Rule("open", Result.PARKED, "noop", False, "owner", wake="answer"),
    Kind.CUT: Rule("none", Result.PAUSED, "paused", False, "none"),
    Kind.ASK_DECISION: _ask(),
    Kind.ASK_STUCK: _ask(replan=True),
    Kind.ASK_BUDGET: _ask(),
    Kind.ASK_TICKET: Rule("block", Result.PARKED, "parked", True, "bead_author", wake="spec"),
    Kind.WAIT_ASK: Rule("none", Result.PARKED, "parked", False, "owner", wake="answer"),
    Kind.PAUSE_ACCOUNT: Rule("open", Result.PAUSED, "paused", False, "account", wake="account"),
    Kind.PAUSE_NETWORK: Rule("open", Result.PAUSED, "paused", False, "network", wake="net"),  # counts toward no cap
    Kind.ENGINE_CRASH: Rule("open", Result.PARKED, "parked", False, "engineer"),
    Kind.PAUSE_KILLED: Rule("open", Result.PAUSED, "paused", False, "none"),
    Kind.PAUSE_MOVED: Rule("open", Result.PAUSED, "paused", False, "host"),  # its needs label keeps this host off; a capable host takes it
    Kind.OWNER_PARK: Rule("open", Result.PARKED, "parked", False, "owner"),
    Kind.FAULT_INFRA: _fault(),
    Kind.FAULT_SLOT: _fault(),
    Kind.FAULT_DENIED: _fault(),
    Kind.FAULT_STALE_BASE: _fault(),
    Kind.FAULT_PLAN: Rule("open", Result.FAILED, "failed", False, "engineer", label="engine-fault",
                          retries=KNOBS["fault_retries"], escalate_to=Kind.ASK_STUCK, replan=True),
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
        if self.kind is Kind.STAGE:
            return Outcome.STAGED
        if self.kind is Kind.NOOP:
            return Outcome.NOOP
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
    events = [Event(str(h.get("bead")), str(h.get("fingerprint")), float(h.get("t") or 0), str(h.get("kind", ""))) for h in history]
    if rule.escalate_to and outcome.fingerprint:
        same = streak(events, bead, outcome.fingerprint, lambda e: e.kind.startswith("ask_"))  # an ask ended the run of identical faults
        if same >= rule.retries:
            kind, rule, escalated = rule.escalate_to, POLICY[rule.escalate_to], True
    said = seen_within(events, bead, kind.value, outcome.fingerprint, now=now, window_s=knobs["comment_dedupe_s"])
    return Disposition(kind, rule.bd, rule.label, rule.loop, rule.trace, rule.makes_ask, not said, escalated)
