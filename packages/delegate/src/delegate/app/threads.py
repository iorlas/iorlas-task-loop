"""Caller thread keys own session selection; the caller supplies whole and delta prompts."""

from pathlib import Path

from delegate.app import env, run_legs
from delegate.contracts import codec
from delegate.contracts.codec import record
from delegate.contracts.json_types import Json, arr, as_num, obj
from delegate.contracts.routing import Routing
from delegate.contracts.state import StateDoc, ThreadRecord
from delegate.contracts.wire import RunRequest, RunResult

TAKEOVER_NOTE = (
    "\nYou take over from an earlier writer of this task, on another model. Its work is in this "
    "tree, committed on this branch or not: read `git status` and the diff from main first, then go on "
    "from there; do not start over."
)


@record
class ThreadPlan:
    key: str
    resume: str | None
    brief_text: str
    takeover: bool


def plan(request: RunRequest, state: StateDoc, routing: Routing) -> ThreadPlan:
    key = f"{request.task}/{request.thread}" if request.thread else ""
    previous = state.threads.get(key) if key else None
    resume = None
    path = request.brief_file
    account = routing.accounts.get(previous.account or "") if previous else None
    limit = routing.settings.fresh_above_k.get(account.family, 0) if account else 0
    if request.boundary and limit > 0 and routing.settings.fresh_stage_k > 0:
        limit = min(limit, routing.settings.fresh_stage_k)
    oversized = previous is not None and previous.context_k is not None and limit > 0 and previous.context_k > limit
    mark = state.out.get(previous.first_account or "") if previous else None
    retake = previous is not None and previous.fallback and (mark is None or mark.until <= env.now())
    if previous is not None and request.delta_file is not None and not oversized and not retake:
        resume, path = previous.ref, request.delta_file
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    takeover = request.role == "worker" and previous is not None and resume is None
    return ThreadPlan(
        key=key,
        resume=resume if key else request.resume,
        brief_text=text + (TAKEOVER_NOTE if takeover else ""),
        takeover=takeover,
    )


def settle(state: StateDoc, key: str, res: RunResult) -> None:
    if not key or not res.ref:
        return
    state.threads.pop(key, None)
    state.threads[key] = ThreadRecord(
        ref=res.ref,
        account=res.account,
        model=res.model,
        context_k=res.usage.context_k,
        fallback=res.fallback is True,
        first_account=res.first_account if isinstance(res.first_account, str) else None,
    )
    for old in list(state.threads)[:-200]:
        del state.threads[old]


def needs_fresh(res: RunResult) -> bool:
    stop = res.stop
    if stop is None:
        return False
    if stop.scope == "caller" and stop.permanence == "needs_owner":
        return True
    if stop.permanence != "transient":
        return False
    return (stop.scope == "bead" and stop.retry.kind in ("none", "predicted")) or (
        stop.scope in ("account", "model") and stop.retry.kind in ("predicted", "poll")
    )


def _attempts(res: dict[str, Json], kind: str) -> list[Json]:
    attempts = arr(res.get("attempts")) or [
        {k: res.get(k) for k in ("account", "model", "secs", "tokens")}
        | {"kind": "first", "outcome": obj(res["stop"]).get("reason") if res["stop"] else None}
    ]
    if kind == "new_thread":
        first = next((obj(a) for a in attempts if obj(a).get("kind") == "first"), obj(attempts[0]))
        first["kind"] = kind
    return attempts


def merge(first: RunResult, last: RunResult) -> RunResult:
    """Adapt finished answers to the leg merger, keeping the last answer's session telemetry."""
    a, b = codec.to_json(first), codec.to_json(last)
    attempts = [*_attempts(a, "first"), *_attempts(b, "new_thread")]
    au, bu = obj(a["usage"]), obj(b["usage"])
    a["acct"], b["acct"] = au | obj(au.get("tokens")), bu | obj(bu.get("tokens"))
    merged = run_legs.merge(a, b)
    acct = obj(merged.pop("acct"))
    merged.pop("cumulative", None)
    merged["secs"] = first.secs + last.secs
    bu.update({k: acct[k] for k in ("cost_usd", "cost_source", "accounting")})
    tokens = obj(merged["tokens"])
    if tokens:
        bu["tokens"] = tokens | {k: acct.get(k) for k in ("in_fresh", "cache_read", "cache_write")}
    for key in ("cost", "secs", "answer_bytes"):
        bu[key] = (as_num(au.get(key)) or 0) + (as_num(bu.get(key)) or 0)
    bu["turns"] = None if au["turns"] is None and bu["turns"] is None else (as_num(au["turns"]) or 0) + (as_num(bu["turns"]) or 0)
    merged["attempts"] = attempts
    return codec.from_json(RunResult, merged)
