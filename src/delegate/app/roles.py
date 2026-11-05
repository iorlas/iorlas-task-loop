"""roles{} for status --json (delegate-0sf, A2.7): per role, may a worker start now (`usable`) and can its vendors be reached (`net`).

Pure: the caller passes a domain `Router`, the lanes, and the cached network probe. No process, no socket. A full `status` computes the
rows; `status --cheap` replays them from the snapshot and refreshes the parts that move without a spawn: `net` (the probe cache), live
holds.
"""

from delegate.adapters import netprobe
from delegate.contracts.json_types import Json, arr, obj
from delegate.contracts.routing import CallArgs, Run
from delegate.domain.lanes import profiles
from delegate.domain.lanes.lane import Lane
from delegate.domain.routing.router import Router


def families(node: Json) -> list[str]:
    """-> every runner family a role's chain names (`"on": family` anywhere inside the role, in order, once)."""
    found: list[str] = []

    def walk(x: Json) -> None:
        if isinstance(x, dict):
            on = x.get("on")
            if isinstance(on, str):
                found.append(on)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(node)
    return list(dict.fromkeys(found))


def role_hosts(role: Json) -> list[str]:
    return list(dict.fromkeys(h for f in families(role) for h in profiles.hosts_for_family(f)))


def roles_view(
    cfg: dict[str, Json], lanes: dict[str, Lane], router: Router, doc: object, t: float, cached_net: dict[str, Json] | None = None
) -> dict[str, dict[str, Json]]:
    """-> {role: {usable, lane, model, why, until, hosts, net}}. `usable` is what `next ROLE` would answer with no flags, in the unattended
    view `until` = when a stopped role is expected back (the soonest lane return), else None.
    `router` is a domain Router; nothing is mutated."""
    out: dict[str, dict[str, Json]] = {}
    for name, role in obj(cfg["roles"]).items():
        hosts = role_hosts(role)
        row: dict[str, Json] = {
            "usable": None,
            "lane": None,
            "model": None,
            "why": None,
            "until": None,
            "hosts": hosts,
            "net": netprobe.view(cached_net, hosts, t),
        }
        try:
            d = router.decide(name, CallArgs(unattended=True), lanes)
        except Exception as e:  # one odd role must not take the status down
            row["why"] = f"{type(e).__name__}: {e}"
            out[name] = row
            continue
        if isinstance(d, Run):
            row.update(usable=True, lane=d.lane, model=d.model)
        else:
            backs = [ln.out_until for ln in lanes.values() if ln.out and ln.out_until and ln.out_until > t]
            backs += [b.until for ln in lanes.values() for b in ln.benched.values() if b.until and b.until > t]
            backs += [h.until for ln in lanes.values() if (h := router.holds.covering(ln.name, name, t)) and h.until > t]
            row.update(usable=False, why=getattr(d, "say", None) or getattr(d, "error", None), until=min(backs) if backs else None)
        out[name] = row
    return out


def refresh(roles: Json, holds: Json, cached_net: dict[str, Json] | None, t: float) -> dict[str, Json]:
    """-> `roles` (from a snapshot) with what moves without a spawn brought up to date: `net` from the probe cache; `usable` False while a
    live hold
    names the role's lane; `due` True when a stopped role's `until` has passed (run a full status to learn whether it is back)."""
    out: dict[str, Json] = {}
    for name, role in obj(roles).items():
        r = dict(obj(role))
        r["net"] = netprobe.view(cached_net, [h for h in arr(r.get("hosts")) if isinstance(h, str)], t)
        for hold in arr(holds):
            h = obj(hold)
            until = h.get("until")
            if (
                r.get("usable")
                and h.get("lane") == r.get("lane")
                and (not h.get("roles") or name in arr(h.get("roles")))
                and (until if isinstance(until, int | float) and until else t + 1) > t
            ):
                r.update(usable=False, why=f"on hold: {h.get('reason') or h.get('id')}", until=until)
        due = r.get("until")
        if r.get("usable") is False and isinstance(due, int | float) and due and due <= t:
            r["due"] = True
        out[name] = r
    return out
