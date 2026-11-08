"""The network probe: one run of adapters/netprobe (sockets only, no process, no vendor call, no quota), its cache file, and the view of
the cache that
`status` shows. `net_up` is the one question the outcome ladder asks when a failure names no cause."""

import json
from collections.abc import Callable, Iterable

from delegate.adapters import netprobe
from delegate.app import env
from delegate.contracts.json_types import Json
from delegate.domain.accounts import profiles


def network_view(cached: dict[str, Json] | None, t: float):
    return dict(netprobe.view(cached, [], t), why=(cached or {}).get("why"))


def net_probe(hosts: Iterable[str] | None = None):
    """-> one probe (adapters/netprobe.py), stored in the net cache. Sockets only: no process, no vendor call, no quota."""
    res = netprobe.probe(hosts)
    netprobe.record(str(env.net_cache_path()), res)
    return res


def net_up(account: str | None = None):
    """True when `account`'s vendor hosts (else all of them) are reachable now. The one question the outcome ladder asks when a failure
    names
    no cause."""
    return bool(net_probe(list(profiles.hosts_of(account)) or None)["up"])


def cmd_net(a: env.Args):
    """route.py net: the probe, as one JSON object. Exit 0 whenever it printed."""
    hosts = list(a.host or []) or list(profiles.hosts_of(a.account)) or list(profiles.all_hosts()) + list(netprobe.NEUTRAL)
    res = net_probe(hosts)
    cached = netprobe.load(str(env.net_cache_path())) or {}
    print(
        json.dumps(
            {
                "v": 1,
                "up": res["up"],
                "ip_up": res["ip_up"],
                "why": res["why"],
                "ms": res["ms"],
                "hosts": res["hosts"],
                "at": res["at"],
                "since": cached.get("since"),
            }
        )
    )
    return 0


NET_BACKOFF = (5, 10, 20, 40, 60, 120)


def wait_up(account: str, cap_s: float, now: Callable[[], float], sleep: Callable[[float], object]) -> tuple[float, bool]:
    """Probe after each backoff, clipping the last sleep to this call's remaining budget."""
    start, index = now(), 0
    while (waited := now() - start) < cap_s:
        sleep(min(NET_BACKOFF[min(index, len(NET_BACKOFF) - 1)], cap_s - waited))
        index += 1
        if net_up(account):
            return min(now() - start, cap_s), True
    return cap_s, False
