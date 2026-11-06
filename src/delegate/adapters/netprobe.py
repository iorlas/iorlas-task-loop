"""Network facts (delegate-4n7, A2.5): is the machine online. The probe, its cache file and the view are the vendored shelf `any_net`;
this is the dict form delegate's status, roles and `route.py net` print (stdlib only, sockets and the cache file, no subprocess, no
quota)."""

import time
from collections.abc import Callable, Iterable
from pathlib import Path

import any_net
from any_net.probe import Connect, Resolve

from delegate.contracts.json_types import Json

NEUTRAL = ("one.one.one.one:443",)
BUDGET_S = 2.5  # whole probe; route.py net answers in under 3 s
FRESH_S = 120  # a cached probe older than this is "unknown"


def _row(p: any_net.Probe) -> dict[str, Json]:
    return {"up": p.up, "ip_up": p.ip_up, "why": p.why, "ms": p.ms, "hosts": dict(p.per_host), "at": p.at, "since": p.since}


def _probe(res: dict[str, Json]) -> any_net.Probe:
    hosts, since, at = res.get("hosts"), res.get("since"), res.get("at")
    per_host = {k: str(v) for k, v in hosts.items()} if isinstance(hosts, dict) else {}
    return any_net.Probe(
        bool(res["up"]), bool(res.get("ip_up")), str(res.get("why") or ""), per_host,
        float(at) if isinstance(at, (int, float)) else 0.0, 0, float(since) if isinstance(since, (int, float)) else None,
    )


def probe(
    hosts: Iterable[str] | None = None,
    budget_s: float = BUDGET_S,
    connect_s: float = 1.5,
    resolve: Resolve | None = None,
    connect: Connect | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Json]:
    """-> {up, ip_up, why, ms, hosts: {host: ok|dns|tcp|slow}, at}; `why`: ok | dns | vendor | offline."""
    if resolve is None and connect is None:
        return _row(any_net.probe(hosts, budget_s, connect_s=connect_s, clock=clock))
    if resolve is None or connect is None:
        msg = "inject resolve and connect together, or neither"
        raise ValueError(msg)
    return _row(any_net.probe(hosts, budget_s, connect_s=connect_s, resolve=resolve, connect=connect, clock=clock))


def record(path: str | Path, res: dict[str, Json], clock: Callable[[], float] = time.time) -> dict[str, Json]:
    """Store a probe in `path` (atomic replace). `since` moves only when up flips. Never raises. -> the stored row."""
    return _row(any_net.record(path, _probe(res)))


def load(path: str | Path) -> dict[str, Json] | None:
    stored = any_net.last(path)
    return _row(stored) if stored else None


def view(cached: dict[str, Json] | None, hosts: Iterable[str], t: float, fresh_s: float = FRESH_S) -> dict[str, Json]:
    """-> {up: True|False|None, since, age_s}; None = no probe, or one older than fresh_s."""
    v = any_net.view(_probe(cached) if cached and isinstance(cached.get("at"), (int, float)) else None, hosts, t, fresh_s)
    return {"up": v.up, "since": v.since, "age_s": v.age_s}
