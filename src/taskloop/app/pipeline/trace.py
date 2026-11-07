"""The run's trace: what the engine knows at the close, as the typed RunTrace the report, the digest and the dashboard read."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from tlkernel import ids, wire
from tlkernel import trace as t
from tlkernel.enums import Outcome, WhyCode
from tlkernel.kinds import Kind
from tlkernel.wire import Rec

WHY_CODE: Mapping[str, WhyCode] = MappingProxyType(
    {
        Kind.ASK_DECISION.value: WhyCode.OWNER_DECISION,
        Kind.ASK_STUCK.value: WhyCode.STUCK,
        Kind.ASK_BUDGET.value: WhyCode.OVER_BUDGET,
        Kind.ASK_TICKET.value: WhyCode.TICKET,
        Kind.WAIT_ASK.value: WhyCode.NEEDS_HUMAN,
        Kind.PAUSE_LANE.value: WhyCode.LANE_OUT,
        Kind.PAUSE_NETWORK.value: WhyCode.NETWORK,
        Kind.ENGINE_CRASH.value: WhyCode.PAUSED,
        Kind.PAUSE_KILLED.value: WhyCode.STOPPED_BY_COORDINATOR,
        Kind.PAUSE_MOVED.value: WhyCode.RESOURCE,
        Kind.OWNER_PARK.value: WhyCode.PAUSED,
        "noop": WhyCode.PAUSED,
        Kind.FAULT_DENIED.value: WhyCode.NEEDS_HUMAN,
        Kind.FAULT_BASE_RED.value: WhyCode.GATE_RED,
        Kind.FAULT_BAD_REQUEST.value: WhyCode.SCHEMA_INVALID,
        Kind.FAULT_LAND.value: WhyCode.CHECK_BEFORE_LAND,
        Kind.FAULT_INFRA.value: WhyCode.FAILED,
        Kind.FAULT_SLOT.value: WhyCode.FAILED,
        Kind.FAULT_STALE_BASE.value: WhyCode.FAILED,
        Kind.FAULT_PLAN.value: WhyCode.FAILED,
        Kind.FAULT_ENGINE.value: WhyCode.FAILED,
        Kind.FAULT_CONTRACT_SKEW.value: WhyCode.FAILED,
        Kind.FAULT_CRASHED.value: WhyCode.FAILED,
    }
)


def why_code(kind: str, outcome: Outcome) -> WhyCode | None:
    """The coarse reason a run ended otherwise than landed or done; the verify-gaps ask has no kind."""
    if outcome in (Outcome.LANDED, Outcome.DONE):
        return None
    return WHY_CODE.get(kind) or (WhyCode.VERIFY if outcome is Outcome.BLOCKED else WhyCode.FAILED)


def _known(cls: type[Rec], row: Mapping[str, Any]) -> dict[str, Any]:
    names = set(wire.names(cls))
    return {k: v for k, v in row.items() if k in names and v is not None}


def ai_call(row: Mapping[str, Any]) -> t.AiCall:
    tk = row.get("tokens") or {}
    kw = _known(t.AiCall, {k: v for k, v in row.items() if k not in ("tokens", "denied")})
    return t.AiCall(
        **kw,
        tokens=t.Tokens(in_=int(tk.get("in") or 0), cached=int(tk.get("cached") or 0), out=int(tk.get("out") or 0)),
        denied=[
            t.Denied(
                tool=str(d.get("tool") or ""), kind=str(d.get("kind") or ""), reason=str(d.get("reason") or ""), input=d.get("input") or {}
            )
            for d in row.get("denied") or []
            if isinstance(d, dict)
        ],
    )


def reflection(r: Mapping[str, Any] | None) -> t.Reflection | None:
    if not r:
        return None
    bad = [t.WentBadly(**{k: str(w.get(k) or "") for k in ("what", "cause", "session", "evidence")}) for w in r.get("went_badly") or []]
    return t.Reflection(
        went_well=list(r.get("went_well") or []), wasted=list(r.get("wasted") or []), change=list(r.get("change") or []), went_badly=bad
    )


def write_round(w: Mapping[str, Any]) -> t.WriteRound:
    return t.WriteRound(
        write=w["write"],
        round=w["round"],
        node_id=w.get("node_id") or 0,
        ref=w.get("ref") or "",
        resumed=w.get("resumed") or "",
        input_tokens=w.get("input_tokens") or 0,
        turns=w.get("turns"),
        prompt_chars=w.get("prompt_chars"),
        context_k=w.get("context_k"),
        fresh=w.get("fresh") or "",
    )


def run_trace(run: str, f: Mapping[str, Any]) -> t.RunTrace:
    """The trace of run `run` from the engine's facts `f` (keys named as RunTrace's fields; sessions, write rounds, verified and
    the reflection as the engine keeps them). Raises ValueError when the run's name is not one."""
    return t.RunTrace(
        run=ids.RunId.parse(run),
        outcome=Outcome(f["outcome"]),
        cost=t.Cost(usd=float(f.get("cost") or 0.0)),
        stats=t.Stats(**_known(t.Stats, f.get("stats") or {})),
        sessions=[ai_call(s) for s in f.get("sessions") or []],
        verified=[
            t.Verified(**{k: str(v.get(k) or "") for k in ("what", "kind", "verdict", "evidence", "why")}) for v in f.get("verified") or []
        ],
        write_rounds=[write_round(w) for w in f.get("write_rounds") or []],
        reflection=reflection(f.get("reflection")),
        strays=[str(x) for x in f.get("strays") or []],
        lane_notes=[str(x) for x in f.get("lane_notes") or []],
        **_known(
            t.RunTrace,
            {
                k: v
                for k, v in f.items()
                if k not in ("outcome", "cost", "stats", "sessions", "verified", "write_rounds", "reflection", "strays", "lane_notes")
            },
        ),
    )
