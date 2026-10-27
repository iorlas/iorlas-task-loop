"""delegate's contract-3 answer (one JSON object) as a `DelegateResult`. Reads are tolerant of keys we do not model; an answer
that breaks the shape becomes a synthesized stop, never an exception. `status` and `next` are derived from `stop` here and
nowhere else (contract 3 removed them from the wire)."""
from typing import Any

from taskloop.contracts.delegate import DelegateResult, Retry, StopFacts, Usage
from taskloop.contracts.trace import Denied, Tokens

CONTRACT = 3
SCOPES = ("bead", "caller", "machine", "lane", "model")
PERMANENCE = ("transient", "needs_owner")
RETRY = ("none", "predicted", "poll")
_FAILED = ("worker_failed", "schema_invalid", "secrets")
_ERROR = ("bad_request", "caller", "setup", "crash", "contract_violation")


def synth(reason: str, scope: str, permanence: str, text: str, ref: str = "", status: str = "") -> DelegateResult:
    """A result delegate did not write: the engine's own account of a call that gave no usable answer."""
    stop = StopFacts(reason=reason, scope=scope, permanence=permanence, retry=Retry(kind="none"), ref=ref)  # type: ignore[arg-type]
    return DelegateResult(status=status_of(stop) if not status else status, reason=reason, next=next_of(stop),  # type: ignore[arg-type]
                          text=text[-2000:], say=text[:300], ref=ref or None, stop=stop)


def status_of(stop: StopFacts | None) -> str:
    if stop is None:
        return "done"
    if stop.reason == "timeout":
        return "timeout"
    if stop.reason in _FAILED:
        return "failed"
    if stop.reason in _ERROR:
        return "error"
    return "lane_out" if stop.scope in ("lane", "model") else "stop"


def next_of(stop: StopFacts | None) -> str | None:
    if stop is None:
        return None
    if stop.permanence == "needs_owner":
        return "owner"
    return "retry" if stop.retry.kind != "none" else "fail"


def _num(v: Any, default: float = 0.0) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def _int(v: Any) -> int:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else 0


def stop_of(raw: Any) -> StopFacts | None:
    if raw is None:
        return None
    r = raw.get("retry") if isinstance(raw, dict) else None
    if not (isinstance(raw, dict) and isinstance(r, dict) and raw.get("scope") in SCOPES
            and raw.get("permanence") in PERMANENCE and r.get("kind") in RETRY and isinstance(raw.get("reason"), str)):
        raise ValueError("stop is not {reason, scope, permanence, retry{kind}}")
    at = r.get("at")
    return StopFacts(reason=raw["reason"], scope=raw["scope"], permanence=raw["permanence"],
                     retry=Retry(kind=r["kind"], at=float(at) if isinstance(at, (int, float)) else None),
                     ref=str(raw.get("ref") or ""), fix=str(raw.get("fix") or ""),
                     resumable=bool(raw.get("resumable")), partial=bool(raw.get("partial")))


def tokens_of(raw: Any) -> Tokens:
    if not isinstance(raw, dict):
        return Tokens()
    if "in_fresh" in raw or "cache_read" in raw:  # usage.tokens: the input split into fresh and cached
        cached = _int(raw.get("cache_read"))
        return Tokens(in_=_int(raw.get("in_fresh")) + cached, cached=cached, out=_int(raw.get("out")))
    return Tokens(in_=_int(raw.get("in")), cached=_int(raw.get("cached")), out=_int(raw.get("out")))


def usage_of(raw: Any) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    turns, ctx = raw.get("turns"), raw.get("context_k")
    return Usage(tokens=tokens_of(raw["tokens"]) if isinstance(raw.get("tokens"), dict) else None,
                 cost=_num(raw.get("cost_usd") if raw.get("cost_usd") is not None else raw.get("cost")),
                 secs=_num(raw.get("secs")), turns=turns if isinstance(turns, int) else None,
                 context_k=_num(ctx) if isinstance(ctx, (int, float)) else None, ref=raw.get("ref") or None)


def denied_of(raw: Any) -> list[Denied]:
    """`sandbox_limit` is noise, never a failure: it is not carried."""
    rows = raw if isinstance(raw, list) else []
    return [Denied(tool=str(d.get("tool") or ""), input=d["input"] if isinstance(d.get("input"), dict) else {})
            for d in rows if isinstance(d, dict) and d.get("kind") != "sandbox_limit"]


def _opt(j: dict[str, Any], key: str) -> str | None:
    v = j.get(key)
    return v if isinstance(v, str) and v else None


def result_of(j: Any) -> DelegateResult:
    if not isinstance(j, dict) or j.get("contract") != CONTRACT or "stop" not in j:
        return synth("contract_violation", "machine", "needs_owner", "an answer that is not delegate contract 3: %.300r" % (j,))
    try:
        stop = stop_of(j["stop"])
    except ValueError as e:
        return synth("contract_violation", "machine", "needs_owner", "%s: %.300r" % (e, j["stop"]), str(j.get("ref") or ""))
    data = j.get("data")
    warnings = j.get("warnings")
    return DelegateResult(
        status=status_of(stop), reason=stop.reason if stop else None, next=next_of(stop),  # type: ignore[arg-type]
        data=data if isinstance(data, dict) else None, text=str(j.get("text") or ""), ref=_opt(j, "ref"),
        lane=str(j.get("lane") or ""), model=str(j.get("model") or ""), effort=str(j.get("effort") or ""),
        family=str(j.get("family") or ""), flag=_opt(j, "flag"), cost=_num(j.get("cost")), tokens=tokens_of(j.get("tokens")),
        denied=denied_of(j.get("denied")), secs=_num(j.get("secs")), run_id=_opt(j, "run_id"), call_id=_opt(j, "call_id"),
        transcript=_opt(j, "transcript"), transcript_status=str(j.get("transcript_status") or ""),
        say=str(j.get("say") or ""), git_violation=[str(x) for x in j.get("git_violation") or []], stop=stop,
        usage=usage_of(j.get("usage")), fallback=_opt(j, "fallback"), first_lane=_opt(j, "first_lane"),
        rung=j["rung"] if isinstance(j.get("rung"), int) else None,
        warnings=[str(x) for x in warnings] if isinstance(warnings, list) else [])
