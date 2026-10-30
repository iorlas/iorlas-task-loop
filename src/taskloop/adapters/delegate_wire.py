"""delegate's contract-3 answer (one JSON object) as a `DelegateResult`. Reads are tolerant of keys we do not model; an answer
that breaks the shape becomes a synthesized stop, never an exception. A status word and a next step are derived from `stop`
here and nowhere else (`answer_status`, `answer_next`): contract 3 removed them from the wire and from `DelegateResult`."""
from typing import Any, get_args

from taskloop.contracts.delegate import (
    REASON_TIMEOUT,
    Accounting,
    CostSource,
    DelegateResult,
    Denial,
    Permanence,
    Retry,
    RetryKind,
    Scope,
    StopFacts,
    Survivor,
    TranscriptInfo,
    TranscriptKind,
    TtlSource,
    Usage,
    UsageTokens,
    WorkerEnd,
    WorkerEndKind,
)
from taskloop.contracts.trace import Tokens

CONTRACT = 3
SCOPES: tuple[Scope, ...] = get_args(Scope)
PERMANENCE: tuple[Permanence, ...] = get_args(Permanence)
RETRY: tuple[RetryKind, ...] = get_args(RetryKind)
TTL_SOURCES: tuple[TtlSource, ...] = get_args(TtlSource)
COST_SOURCES: tuple[CostSource, ...] = get_args(CostSource)
ACCOUNTING: tuple[Accounting, ...] = get_args(Accounting)
TRANSCRIPTS: tuple[TranscriptKind, ...] = get_args(TranscriptKind)
ENDS: tuple[WorkerEndKind, ...] = get_args(WorkerEndKind)
_FAILED = ("worker_failed", "schema_invalid", "secrets")
_ERROR = ("bad_request", "caller", "setup", "crash", "contract_violation")


def synth(reason: str, scope: Scope, permanence: Permanence, text: str, ref: str = "") -> DelegateResult:
    """A result delegate did not write: the engine's own account of a call that gave no usable answer."""
    stop = StopFacts(reason=reason, scope=scope, permanence=permanence, retry=Retry(kind="none"), ref=ref)
    return DelegateResult(text=text[-2000:], say=text[:300], ref=ref or None, stop=stop)


def answer_status(res: DelegateResult) -> str:
    """done | agent (the agent-tool handoff) | timeout | failed | error | lane_out | stop."""
    return "agent" if res.stop is None and res.agent_model else status_of(res.stop)


def answer_next(res: DelegateResult) -> str | None:
    return next_of(res.stop)


def status_of(stop: StopFacts | None) -> str:
    if stop is None:
        return "done"
    if stop.reason == REASON_TIMEOUT:
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
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def stop_of(raw: Any) -> StopFacts | None:
    if raw is None:
        return None
    r = raw.get("retry") if isinstance(raw, dict) else None
    if not (isinstance(raw, dict) and isinstance(r, dict) and isinstance(raw.get("reason"), str)):
        raise ValueError("stop is not {reason, scope, permanence, retry{kind}}")
    scope, permanence, kind = _choice(raw.get("scope"), SCOPES), _choice(raw.get("permanence"), PERMANENCE), _choice(r.get("kind"), RETRY)
    if scope is None or permanence is None or kind is None:
        raise ValueError("stop is not {reason, scope, permanence, retry{kind}}")
    at = r.get("at")
    return StopFacts(reason=raw["reason"], scope=scope, permanence=permanence,
                     retry=Retry(kind=kind, at=float(at) if isinstance(at, (int, float)) else None),
                     ref=str(raw.get("ref") or ""), fix=str(raw.get("fix") or ""),
                     resumable=bool(raw.get("resumable")), partial=bool(raw.get("partial")))


def tokens_of(raw: Any) -> Tokens | None:
    if not isinstance(raw, dict):
        return None
    return Tokens(in_=_int(raw.get("in")), cached=_int(raw.get("cached")), out=_int(raw.get("out")))


def _oint(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _choice[L: str](v: object, allowed: tuple[L, ...]) -> L | None:
    """The member of `allowed` that `v` names, typed as that member; None for anything else."""
    return next((a for a in allowed if a == v), None)


def pick[L: str](v: object, allowed: tuple[L, ...], default: L) -> L:
    return _choice(v, allowed) or default


def usage_tokens_of(raw: Any) -> UsageTokens | None:
    """Per call, as the wire has it: the uncached input apart from the cache reads and writes."""
    if not isinstance(raw, dict):
        return None
    by_ttl = raw.get("cache_write_by_ttl")
    return UsageTokens(in_fresh=_oint(raw.get("in_fresh")), cache_read=_oint(raw.get("cache_read")),
                       cache_write=_oint(raw.get("cache_write")), out=_oint(raw.get("out")),
                       cache_write_by_ttl={str(k): _int(v) for k, v in by_ttl.items()} if isinstance(by_ttl, dict) else None)


def usage_of(raw: Any) -> Usage | None:
    if not isinstance(raw, dict):
        return None
    turns, ctx, cost = raw.get("turns"), raw.get("context_k"), raw.get("cost_usd")
    return Usage(tokens=usage_tokens_of(raw.get("tokens")), cost=_num(raw.get("cost")), secs=_num(raw.get("secs")),
                 turns=turns if isinstance(turns, int) else None, context_k=_num(ctx) if isinstance(ctx, (int, float)) else None,
                 answer_bytes=_int(raw.get("answer_bytes")), ref=_opt(raw, "ref"), last_activity_at=_opt(raw, "last_activity_at"),
                 warm_until=_opt(raw, "warm_until"), ttl_s=_oint(raw.get("ttl_s")),
                 ttl_source=pick(raw.get("ttl_source"), TTL_SOURCES, "unknown"),
                 cost_usd=_num(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
                 cost_source=pick(raw.get("cost_source"), COST_SOURCES, "unknown"),
                 accounting=pick(raw.get("accounting"), ACCOUNTING, "unknown"))


def denied_of(raw: Any) -> list[Denial]:
    """`sandbox_limit` is noise, never a failure: it is not carried."""
    rows = raw if isinstance(raw, list) else []
    return [Denial(kind=pick(d.get("kind"), ("policy", "secret"), "policy"),
                   tool=_opt(d, "tool"), path=_opt(d, "path"), input=d["input"] if isinstance(d.get("input"), dict) else {})
            for d in rows if isinstance(d, dict) and d.get("kind") != "sandbox_limit"]


def transcript_info_of(raw: Any) -> TranscriptInfo | None:
    kind = _choice(raw.get("kind"), TRANSCRIPTS) if isinstance(raw, dict) else None
    if not (isinstance(raw, dict) and isinstance(raw.get("path"), str) and kind is not None):
        return None
    return TranscriptInfo(path=raw["path"], kind=kind, from_=_int(raw.get("from")), to=_int(raw.get("to")),
                          bytes=_int(raw.get("bytes")))


def _opt(j: dict[str, Any], key: str) -> str | None:
    v = j.get(key)
    return v if isinstance(v, str) and v else None


def worker_of(raw: Any) -> WorkerEnd | None:
    """`worker` of the answer: how delegate ended the worker's life. A survivor is a pid that outlived SIGTERM and SIGKILL."""
    if not isinstance(raw, dict):
        return None
    return WorkerEnd(end=pick(raw.get("end"), ENDS, "ok"), stopped=bool(raw.get("stopped")),
                     term_sent=bool(raw.get("term_sent")), kill_sent=bool(raw.get("kill_sent")), waited_s=_num(raw.get("waited_s")),
                     survivors=[Survivor(pid=s["pid"], start=_opt(s, "start")) for s in raw.get("survivors") or []
                                if isinstance(s, dict) and isinstance(s.get("pid"), int)],
                     pid=_oint(raw.get("pid")), pgid=_oint(raw.get("pgid")), start=_opt(raw, "start"))


def _dict(v: Any) -> dict[str, Any] | None:
    return v if isinstance(v, dict) else None


def result_of(j: Any) -> DelegateResult:
    if not isinstance(j, dict) or j.get("contract") != CONTRACT or "stop" not in j:
        return synth("contract_violation", "machine", "needs_owner", f"an answer that is not delegate contract 3: {j!r:.300}")
    try:
        stop = stop_of(j["stop"])
    except ValueError as e:
        return synth("contract_violation", "machine", "needs_owner", "{}: {!r:.300}".format(e, j["stop"]), str(j.get("ref") or ""))
    warnings = j.get("warnings")
    return DelegateResult(
        stop=stop, data=_dict(j.get("data")), text=str(j.get("text") or ""), ref=_opt(j, "ref"),
        lane=_opt(j, "lane"), model=_opt(j, "model"), effort=_opt(j, "effort"), family=_opt(j, "family"), flag=_opt(j, "flag"),
        cost=_num(j.get("cost")), tokens=tokens_of(j.get("tokens")), denied=denied_of(j.get("denied")), secs=_num(j.get("secs")),
        run_id=_opt(j, "run_id"), call_id=_opt(j, "call_id"), transcript=_opt(j, "transcript"),
        transcript_info=transcript_info_of(j.get("transcript_info")), transcript_status=_opt(j, "transcript_status"),
        say=str(j.get("say") or ""), git_violation=[str(x) for x in j.get("git_violation") or []], usage=usage_of(j.get("usage")),
        context=_dict(j.get("context")), worker=worker_of(j.get("worker")), exit_code=_oint(j.get("exit_code")),
        first_error=str(j.get("first_error") or ""), fallback=j.get("fallback") if isinstance(j.get("fallback"), bool) else None,
        first_lane=_opt(j, "first_lane"), warning=str(j.get("warning") or ""), ask_kind=str(j.get("ask_kind") or ""),
        warnings=[str(x) for x in warnings] if isinstance(warnings, list) else [], agent_model=_opt(j, "agent_model"))
