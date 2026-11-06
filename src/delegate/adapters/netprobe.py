"""Network facts (delegate-4n7, A2.5): is the machine online, and (classify.py) whether a text says a connection dropped.

Pure but for sockets and the cache file it is given. stdlib only, no subprocess, no vendor call, so a probe costs no quota.
`probe()` resolves each host and opens a TCP connection to it, all hosts at once, and gives up on the whole thing after `budget_s`
(socket.getaddrinfo ignores socket timeouts, so the join deadline is what bounds the call). `up` means a vendor name resolved AND
connected: a neutral IP literal that answers while names do not is reported as `ip_up`, because that is a DNS outage and the vendor is
still unreachable.
"""

import contextlib
import json
import re
import socket
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from atomic_io import atomic_write_text

from delegate.contracts.json_types import Json

Resolve = Callable[[str, int], str]  # name, port -> address
Connect = Callable[[tuple[str, int], float], None]  # (address, port), timeout -> returns or raises OSError
BUDGET_S = 2.5  # whole probe; route.py net answers in under 3 s
CONNECT_S = 1.5  # one TCP connect
FRESH_S = 120  # a cached probe older than this is "unknown"
NEUTRAL = ("one.one.one.one:443",)  # a name every resolver knows: the fallback when no vendor host is given
IP_LITERAL = "1.1.1.1:443"  # no DNS: separates "offline" from "DNS is down"


def split_host(h: str, default_port: int = 443):
    h = h.strip()
    if h.count(":") == 1 and h.rsplit(":", 1)[1].isdigit():
        name, port = h.rsplit(":", 1)
        return name, int(port)
    return h, default_port


def literal(name: str):
    return bool(re.fullmatch(r"\d+\.\d+\.\d+\.\d+", name))


def _try(host: str, out: dict[str, str], connect_s: float, resolve: Resolve, connect: Connect) -> None:
    name, port = split_host(host)
    try:
        addr = name if literal(name) else resolve(name, port)
    except OSError, UnicodeError:
        out[host] = "dns"
        return
    try:
        connect((addr, port), connect_s)
        out[host] = "ok"
    except OSError:
        out[host] = "tcp"


def _resolve(name: str, port: int) -> str:
    return str(socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)[0][4][0])


def _connect(addr: tuple[str, int], timeout: float) -> None:
    socket.create_connection(addr, timeout).close()


def probe(
    hosts: Iterable[str] | None = None,
    budget_s: float = BUDGET_S,
    connect_s: float = CONNECT_S,
    resolve: Resolve = _resolve,
    connect: Connect = _connect,
    clock: Callable[[], float] = time.time,
) -> dict[str, Json]:
    """-> {up, ip_up, why, ms, hosts: {host: ok|dns|tcp|slow}, at}. `hosts` are vendor hosts ("name" or "name:port"); the neutral ones are
    added when none is given. `why`: ok | dns (names do not resolve, the IP literal connects) | vendor (names resolve, the vendor host
    refuses, the IP literal connects) | offline."""
    t0 = time.monotonic()
    names = list(dict.fromkeys(hosts or NEUTRAL))
    allh = [*names, IP_LITERAL]
    out: dict[str, str] = {}
    threads = [threading.Thread(target=_try, args=(h, out, connect_s, resolve, connect), daemon=True) for h in allh]
    for th in threads:
        th.start()
    for th in threads:
        th.join(max(0.0, budget_s - (time.monotonic() - t0)))
    res = {h: out.get(h, "slow") for h in allh}
    up = any(res[h] == "ok" for h in names)
    ip_up = res[IP_LITERAL] == "ok"
    return {
        "up": up,
        "ip_up": ip_up,
        "why": "ok" if up else "dns" if ip_up and any(res[h] == "dns" for h in names) else "vendor" if ip_up else "offline",
        "ms": int((time.monotonic() - t0) * 1000),
        "hosts": dict(res),
        "at": clock(),
    }


# ---- the cache: written by `route.py net` and by every probe a run makes, read by status --cheap (which opens no socket) --------------


def record(path: str | Path, res: dict[str, Json], clock: Callable[[], float] = time.time) -> dict[str, Json]:
    """Store a probe in `path` (atomic replace). `since` moves only when up flips, so outages are countable. -> the stored dict.
    Never raises."""
    prev = load(path) or {}
    since = prev.get("since") if prev.get("up") == res["up"] and prev.get("since") else res["at"]
    row: dict[str, Json] = {
        "v": 1,
        "up": res["up"],
        "ip_up": res["ip_up"],
        "why": res["why"],
        "hosts": res["hosts"],
        "at": res["at"],
        "since": since,
    }
    with contextlib.suppress(OSError):
        atomic_write_text(Path(path), json.dumps(row), fsync=False)
    return row


def load(path: str | Path) -> dict[str, Json] | None:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("at"), (int, float)) else None
    except OSError, ValueError:
        return None


def view(cached: dict[str, Json] | None, hosts: Iterable[str], t: float, fresh_s: float = FRESH_S) -> dict[str, Json]:
    """-> {up: True|False|None, since, age_s} for a set of vendor `hosts` from a cached probe. None = no probe, or one older than fresh_s.
    A host the probe did not test says nothing; when none of them was tested the answer is the probe's overall `up`."""
    at = cached.get("at") if cached else None
    if not cached or not isinstance(at, (int, float)):
        return {"up": None, "since": None, "age_s": None}
    if t - at > fresh_s:
        return {"up": None, "since": cached.get("since"), "age_s": int(t - at)}
    probed = cached.get("hosts")
    tested = probed if isinstance(probed, dict) else {}
    seen = [tested[h] for h in hosts if h in tested]
    up = any(x == "ok" for x in seen) if seen else bool(cached["up"])
    return {"up": up, "since": cached.get("since"), "age_s": int(t - at)}
