"""An online probe that splits DNS from TCP, and a one-file cache of its result."""

from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

Resolve = Callable[[str, int], str]
"""name, port -> address; raises OSError when the name does not resolve."""
Connect = Callable[[tuple[str, int], float], None]
"""(address, port), timeout -> returns, or raises OSError."""

NEUTRAL = ("one.one.one.one:443",)  # a name every resolver knows: used when no host is given
IP_LITERAL = "1.1.1.1:443"  # needs no DNS: separates "offline" from "DNS is down"
_IPV4 = re.compile(r"\d+\.\d+\.\d+\.\d+")


@dataclass(frozen=True)
class Probe:
    """`per_host` maps each tested host (the IP literal included) to ok | dns | tcp | slow.

    `up`: a named host resolved and connected. `ip_up`: the IP literal connected.
    `why`: ok | dns (names fail, the literal answers) | vendor (names resolve, the host refuses, the literal answers) | offline.
    `since` is set by `record`/`cached`: when `up` last flipped.
    """

    up: bool
    ip_up: bool
    why: str
    per_host: dict[str, str]
    at: float
    ms: int = 0
    since: float | None = None


def _split(host: str) -> tuple[str, int]:
    host = host.strip()
    if host.count(":") == 1 and host.rsplit(":", 1)[1].isdigit():
        name, port = host.rsplit(":", 1)
        return name, int(port)
    return host, 443


def _resolve(name: str, port: int) -> str:
    return str(socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)[0][4][0])


def _connect(addr: tuple[str, int], timeout: float) -> None:
    socket.create_connection(addr, timeout).close()


def _try(host: str, out: dict[str, str], connect_s: float, resolve: Resolve, connect: Connect) -> None:
    name, port = _split(host)
    try:
        addr = name if _IPV4.fullmatch(name) else resolve(name, port)
    except (OSError, UnicodeError):
        out[host] = "dns"
        return
    try:
        connect((addr, port), connect_s)
        out[host] = "ok"
    except OSError:
        out[host] = "tcp"


def probe(
    hosts: Iterable[str] | None = None,
    budget_s: float = 2.5,
    *,
    connect_s: float = 1.5,
    resolve: Resolve = _resolve,
    connect: Connect = _connect,
    clock: Callable[[], float] = time.time,
) -> Probe:
    """Resolve and connect to every host at once; the join deadline `budget_s` bounds the whole call.

    `getaddrinfo` ignores socket timeouts, so a host still running at the deadline is reported `slow`.
    `hosts` are "name" or "name:port"; the neutral host is used when none is given.
    """
    t0 = time.monotonic()
    names = list(dict.fromkeys(hosts or NEUTRAL))
    every = [*names, IP_LITERAL]
    out: dict[str, str] = {}
    threads = [threading.Thread(target=_try, args=(h, out, connect_s, resolve, connect), daemon=True) for h in every]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, budget_s - (time.monotonic() - t0)))
    per_host = {h: out.get(h, "slow") for h in every}
    up = any(per_host[h] == "ok" for h in names)
    ip_up = per_host[IP_LITERAL] == "ok"
    why = "ok" if up else "dns" if ip_up and any(per_host[h] == "dns" for h in names) else "vendor" if ip_up else "offline"
    return Probe(up, ip_up, why, per_host, clock(), int((time.monotonic() - t0) * 1000))


def record(path: str | Path, result: Probe) -> Probe:
    """Store `result` in `path` (atomic replace) and return it with `since` set. Never raises.

    `since` moves only when `up` flips, so an outage can be dated.
    """
    prev = last(path)
    since = prev.since if prev is not None and prev.up == result.up and prev.since else result.at
    stored = Probe(result.up, result.ip_up, result.why, result.per_host, result.at, result.ms, since)
    row = {
        "v": 1,
        "up": stored.up,
        "ip_up": stored.ip_up,
        "why": stored.why,
        "hosts": stored.per_host,
        "at": stored.at,
        "ms": stored.ms,
        "since": since,
    }
    target = Path(path)
    tmp = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(row, f)
        Path(tmp).replace(target)
    except (OSError, ValueError):
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)
    return stored


def last(path: str | Path) -> Probe | None:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return Probe(bool(d["up"]), bool(d["ip_up"]), str(d["why"]), dict(d["hosts"]), float(d["at"]), int(d.get("ms", 0)), d.get("since"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached(path: str | Path, fresh_s: float = 120, *, clock: Callable[[], float] = time.time) -> Probe | None:
    """The probe stored in `path`, or None when absent, unreadable or older than `fresh_s`. Opens no socket."""
    stored = last(path)
    return stored if stored is not None and clock() - stored.at <= fresh_s else None


@dataclass(frozen=True)
class View:
    """`up` is None when there is no probe or it is older than `fresh_s`; `since` and `age_s` survive staleness."""

    up: bool | None
    since: float | None
    age_s: int | None


def view(stored: Probe | None, hosts: Iterable[str], now: float, fresh_s: float = 120) -> View:
    """What a stored probe says about `hosts`, for a status read that opens no socket.

    A host the probe did not test says nothing; when none of them was tested the answer is the probe's overall `up`.
    """
    if stored is None:
        return View(None, None, None)
    age = int(now - stored.at)
    if now - stored.at > fresh_s:
        return View(None, stored.since, age)
    seen = [stored.per_host[h] for h in hosts if h in stored.per_host]
    return View(any(x == "ok" for x in seen) if seen else stored.up, stored.since, age)
