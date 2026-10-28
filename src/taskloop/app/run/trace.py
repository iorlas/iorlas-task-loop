"""The run's trace: what the engine knows at the close, as the typed RunTrace the report, the digest and the dashboard read."""
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from taskloop.contracts import ids
from taskloop.contracts import trace as t
from taskloop.contracts.enums import Outcome, WhyCode

WHY_CODE: Mapping[str, WhyCode] = MappingProxyType({
    "ask_decision": WhyCode.OWNER_DECISION, "ask_stuck": WhyCode.STUCK, "ask_budget": WhyCode.OVER_BUDGET, "ask_ticket": WhyCode.TICKET,
    "wait_ask": WhyCode.NEEDS_HUMAN, "pause_lane": WhyCode.LANE_OUT, "pause_network": WhyCode.NETWORK,
    "pause_killed": WhyCode.STOPPED_BY_COORDINATOR, "fault_denied": WhyCode.NEEDS_HUMAN, "fault_base_red": WhyCode.GATE_RED,
    "fault_bad_request": WhyCode.SCHEMA_INVALID, "fault_land": WhyCode.CHECK_BEFORE_LAND, "fault_infra": WhyCode.FAILED,
    "fault_slot": WhyCode.FAILED, "fault_stale_base": WhyCode.FAILED, "fault_plan": WhyCode.FAILED, "fault_engine": WhyCode.FAILED,
    "fault_contract_skew": WhyCode.FAILED, "fault_crashed": WhyCode.FAILED})


def why_code(kind: str, outcome: str) -> WhyCode | None:
    """The coarse reason a run ended otherwise than landed or done; the verify-gaps ask has no kind."""
    if outcome in ("landed", "done"):
        return None
    return WHY_CODE.get(kind) or (WhyCode.VERIFY if outcome == "blocked" else WhyCode.FAILED)


def _known(cls: type, row: Mapping[str, Any]) -> dict[str, Any]:
    names = {f for f in cls.__dataclass_fields__}
    return {k: v for k, v in row.items() if k in names and v is not None}


def ai_call(row: Mapping[str, Any]) -> t.AiCall:
    tk = row.get("tokens") or {}
    kw = _known(t.AiCall, {k: v for k, v in row.items() if k not in ("tokens", "denied")})
    return t.AiCall(**kw, tokens=t.Tokens(in_=int(tk.get("in") or 0), cached=int(tk.get("cached") or 0), out=int(tk.get("out") or 0)),
                    denied=[t.Denied(tool=str(d.get("tool") or ""), input=d.get("input") or {}) for d in row.get("denied") or [] if isinstance(d, dict)])


def reflection(r: Mapping[str, Any] | None) -> t.Reflection | None:
    if not r:
        return None
    bad = [t.WentBadly(**{k: str(w.get(k) or "") for k in ("what", "cause", "session", "evidence")}) for w in r.get("went_badly") or []]
    return t.Reflection(went_well=list(r.get("went_well") or []), wasted=list(r.get("wasted") or []), change=list(r.get("change") or []),
                        went_badly=bad)


def write_round(w: Mapping[str, Any]) -> t.WriteRound:
    return t.WriteRound(write=w["write"], round=w["round"], node_id=w.get("node_id") or 0, ref=w.get("ref") or "", resumed=w.get("resumed") or "",
                        input_tokens=w.get("input_tokens") or 0, turns=w.get("turns"), prompt_chars=w.get("prompt_chars"),
                        context_k=w.get("context_k"), fresh=w.get("fresh") or "")


def run_trace(run: str, f: Mapping[str, Any]) -> t.RunTrace:
    """The trace of run `run` from the engine's facts `f` (keys named as RunTrace's fields; sessions, write rounds, verified and
    the reflection as the engine keeps them). Raises ValueError when the run's name is not one."""
    return t.RunTrace(
        run=ids.RunId.parse(run), outcome=Outcome(f["outcome"]), cost=t.Cost(usd=float(f.get("cost") or 0.0)),
        stats=t.Stats(**_known(t.Stats, f.get("stats") or {})), sessions=[ai_call(s) for s in f.get("sessions") or []],
        verified=[t.Verified(**{k: str(v.get(k) or "") for k in ("what", "kind", "verdict", "evidence", "why")}) for v in f.get("verified") or []],
        write_rounds=[write_round(w) for w in f.get("write_rounds") or []], reflection=reflection(f.get("reflection")),
        strays=[str(x) for x in f.get("strays") or []], lane_notes=[str(x) for x in f.get("lane_notes") or []],
        **_known(t.RunTrace, {k: v for k, v in f.items() if k not in ("outcome", "cost", "stats", "sessions", "verified", "write_rounds",
                                                                         "reflection", "strays", "lane_notes")}))
