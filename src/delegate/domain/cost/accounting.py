"""Per-call usage and cost accounting (delegate-uk0, study 85). Pure functions: the launchers feed them what their harness reported.

An accounting record `acct` is {in_fresh, cache_read, cache_write, out, cost_usd, cost_source, accounting, ttl_s, ttl_source,
cache_write_by_ttl?}. Counts are per call, never cumulative. cache_write and cost_usd are None where the vendor does not report them. No
price table here: cost is what the harness returned, or unknown. warm_until is telemetry (when the vendor's prompt cache probably expires);
nothing routes on it."""

import datetime as dt
from collections.abc import Iterable, Mapping

from delegate.contracts.json_types import Json
from delegate.domain.jsonval import num, obj

type Acct = dict[str, Json]

CODEX_TTL_S = 3600  # measured 65 min (study 85); the vendor states 5-10 min to 24 h


def per_call(total: Mapping[str, Json] | None, before: Mapping[str, Json] | None) -> Mapping[str, Json] | None:
    """A running thread total ({in, cached, out}) minus the total the thread held before this call. `codex exec resume` reports the
    running total; a total lower than before is not a running total of that thread, so it stands as given."""
    if not total or not before or num(total.get("in")) < num(before["in"]):
        return total
    return {k: max(0, num(total.get(k)) - num(before[k])) for k in before}


def last_cumulative(rows: Iterable[Mapping[str, Json]], ref: str | None) -> dict[str, Json] | None:
    """The thread total a history row recorded for `ref` (newest wins), or None."""
    for r in reversed(list(rows)):
        cumulative = r.get("cumulative")
        if r.get("ref") == ref and isinstance(cumulative, dict):
            return cumulative
    return None


def codex(tokens: Mapping[str, Json] | None) -> Acct | None:
    """Per-call {in, cached, out} (already net of a resumed thread's earlier total) -> acct. Codex returns no cost."""
    t = tokens or {}
    cached = num(t.get("cached"))
    return (
        {
            "in_fresh": max(0, num(t.get("in")) - cached),
            "cache_read": cached,
            "cache_write": None,
            "out": num(t.get("out")),
            "cost_usd": None,
            "cost_source": "unknown",
            "accounting": "exact",
            "ttl_s": CODEX_TTL_S,
            "ttl_source": "observed",
        }
        if tokens
        else None
    )


def opencode_step(acct: Acct | None, tokens: Mapping[str, Json], cost: Json) -> Acct:
    """Fold one opencode step-finish (tokens {input, output, reasoning, cache{read,write}}, cost) into the running acct."""
    c = obj(tokens.get("cache"))
    a: Acct = acct or {
        "in_fresh": 0,
        "cache_read": 0,
        "cache_write": 0,
        "out": 0,
        "cost_usd": None,
        "ttl_s": None,
        "ttl_source": "unknown",
    }
    a["in_fresh"] = num(a["in_fresh"]) + num(tokens.get("input"))
    a["cache_read"] = num(a["cache_read"]) + num(c.get("read"))
    a["cache_write"] = num(a["cache_write"]) + num(c.get("write"))
    a["out"] = num(a["out"]) + num(tokens.get("output")) + num(tokens.get("reasoning"))
    if isinstance(cost, int | float):
        a["cost_usd"] = (num(a["cost_usd"]) or 0.0) + float(cost)
    return a


def opencode_close(acct: Acct | None, lane: str) -> Acct | None:
    """Name the cost's source once the steps are in. Grok: opencode's catalog price per step. zai: its steps carry 0 and study 81 found
    that unverifiable, so unknown. Free DeepSeek: free."""
    if not acct:
        return None
    if lane == "ZAI_CODING_SUBSCRIPTION":
        acct.update(cost_usd=None, cost_source="unknown", accounting="unknown")
    elif lane == "DEEPSEEK_FREE":
        acct.update(cost_usd=0.0, cost_source="free", accounting="estimated")
    elif acct["cost_usd"] is None:
        acct.update(cost_source="unknown", accounting="unknown")
    else:
        acct.update(cost_source="harness", accounting="estimated")
    return acct


def merge(a: Acct | None, b: Acct | None) -> Acct | None:
    """Two calls of one run (the schema re-ask) -> one acct; unknown cost stays unknown only if both are."""
    if not a or not b:
        return a or b
    out = dict(b)
    for k in ("in_fresh", "cache_read", "out"):
        out[k] = num(a.get(k)) + num(b.get(k))
    out["cache_write"] = (
        None if a.get("cache_write") is None and b.get("cache_write") is None else num(a.get("cache_write")) + num(b.get("cache_write"))
    )
    costs = [num(x["cost_usd"]) for x in (a, b) if x.get("cost_usd") is not None]
    out["cost_usd"] = sum(costs) if costs else None
    if costs and out["cost_source"] == "unknown":
        out["cost_source"] = "harness"
    return out


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fields(acct: Acct | None, ref: str | None, ended_at: float) -> dict[str, Json]:
    """-> the additive `usage` keys for a finished call (acct may be None: a call that reported nothing)."""
    a: Acct = acct or {}
    ttl = num(a.get("ttl_s")) if ref else None
    return {
        "ref": ref,
        "last_activity_at": iso(ended_at) if ref else None,
        "warm_until": iso(ended_at + ttl) if ttl else None,
        "ttl_s": ttl or None,
        "ttl_source": a.get("ttl_source") if ttl else "unknown",
        "cost_usd": a.get("cost_usd"),
        "cost_source": a.get("cost_source") or "unknown",
        "accounting": a.get("accounting") or "unknown",
    }


def token_fields(acct: Acct | None) -> dict[str, Json]:
    """The per-call counts, added to usage.tokens beside the old in/cached/out."""
    if not acct:
        return {}
    out = {k: acct.get(k) for k in ("in_fresh", "cache_read", "cache_write", "out")}
    if acct.get("cache_write_by_ttl"):
        out["cache_write_by_ttl"] = acct["cache_write_by_ttl"]
    return out
