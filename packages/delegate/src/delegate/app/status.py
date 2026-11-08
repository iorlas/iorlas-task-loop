"""`status`: the payload (accounts, cockpit, running, holds, asks, health, roles, network), the snapshot it leaves for `status --cheap`, and
the network
probe cache. `--cheap` spawns nothing: the last snapshot plus the cached logins, with the leases read fresh."""

import contextlib
import json
from dataclasses import replace

from atomic_io import atomic_write_text

from delegate.adapters import netprobe
from delegate.app import cockpit, decide, env, net, roles, usage
from delegate.app.fleet import settle_holds
from delegate.contracts import codec
from delegate.contracts import status as wire
from delegate.contracts.json_types import Json, as_num
from delegate.contracts.state import StateDoc
from delegate.domain.accounts.account import Account
from delegate.domain.accounts.leases import LeaseBook, suspect
from delegate.domain.health import ledger as health_ledger
from delegate.domain.holds.book import HoldBook
from delegate.domain.routing.router import Router


def status_payload(cfg: dict[str, Json], accounts: dict[str, Account], ck: dict[str, Json], st: StateDoc, t: float) -> dict[str, Json]:
    """The answer, passed through contracts/status.py: a key or type the schema in contract.json does not name fails here, not at a
    caller."""
    return codec.to_json(codec.from_json(wire.Status, _raw_payload(cfg, accounts, ck, st, t)))


def _raw_payload(cfg: dict[str, Json], accounts: dict[str, Account], ck: dict[str, Json], st: StateDoc, t: float):
    return {
        "v": 1,
        "ts": t,
        "accounts": {
            n: {
                "family": ln.family,
                "kind": ln.kind,
                "out": ln.out,
                "out_until": ln.out_until,
                "reason": ln.out_reason if ln.out else None,
                "five": ln.five,
                "week": ln.week,
                "pace": ln.pace,
                "burn": ln.burn,
                "notes": ln.notes,
            }
            for n, ln in accounts.items()
        },
        "cockpit": ck,
        "running": running_rows(st, t),
        "needs_input": cockpit.needs_input(accounts),
        "holds": HoldBook(st.holds).rows(t),
        "asks": [x.as_dict() for x in settle_holds(env.states(), accounts, st, t)[0]],
        "health": health_rows(cfg, accounts, st, t),
        **roles_payload(cfg, accounts, st, t),
    }


def roles_payload(cfg: dict[str, Json], accounts: dict[str, Account], st: StateDoc, t: float):
    """roles{} (usable and net per role) and network{} for status --json; the probe is read from its cache, never run here."""
    cached = netprobe.load(str(env.net_cache_path()))
    routing = env.typed_routing(cfg)
    router = Router(routing, HoldBook(st.holds), st.prev, t)
    return {"roles": roles.roles_view(cfg, accounts, router, st, t, cached), "network": net.network_view(cached, t)}


def health_rows(cfg: dict[str, Json], accounts: dict[str, Account], st: StateDoc, t: float):
    """One row per (account, model): state (up|busy|exhausted|logged_out|held|broken), until, source, evidence, leases{live,suspect},
    last_failures[3]."""
    rows: list[dict[str, Json]] = []
    pol = env.settings_of(cfg).breaker
    for name, ln in accounts.items():
        cnt = LeaseBook(st.leases).counts(name, t)
        rec = st.out.get(name)
        ats = [a for w in ln.windows if (a := as_num(w.get("at")))]
        stale = health_ledger.stale_usage(max(ats) if ats else ln.read_at, t, pol)
        for model, pv in ln.hview.items():
            v = pv
            if v.state == "up" and ln.out and not ln.busy:  # the account's own out record (state.json) is the other half of "exhausted"
                v = replace(
                    v,
                    state="logged_out" if ln.out_reason == "logged_out" else "exhausted",
                    until=ln.out_until,
                    source=rec.source if rec else None,
                    kind=ln.out_reason,
                    evidence=(rec.why if rec else "")[:240],
                )
            state = health_ledger.combine(v, False, ln.busy)
            d = v.as_dict()
            rows.append(
                {
                    "account": name,
                    "model": model,
                    "state": state,
                    "until": d["until"],
                    "source": d["source"],
                    "kind": d["kind"],
                    "evidence": d["evidence"],
                    "canary": d["canary"],
                    "rung": d["rung"],
                    "leases": cnt,
                    "last_failures": d["last_failures"],
                    "needs_login": state == "logged_out" and ln.family == "claude",
                    "usage": {"known": ln.usage_known and not stale, "text": f"unknown (stale {stale:g} h)" if stale else None},
                }
            )
    return rows


def running_rows(st: StateDoc, t: float):
    return [
        {
            "run_id": k,
            "account": v.account,
            "role": v.role,
            "task": v.task,
            "started": v.start,
            "age_s": int(t - v.start),
            "pid": v.pid,
            "worker_pid": v.worker_pid,
            "suspect": suspect(v, t),
        }
        for k, v in sorted(LeaseBook(st.leases).live(t).items(), key=lambda kv: kv[1].start)
    ]


def write_snapshot(payload: dict[str, Json]):
    with contextlib.suppress(Exception):
        p = env.snapshot_path()
        atomic_write_text(p, json.dumps(payload), fsync=False)


def cmd_status_cheap(a: env.Args, cfg: dict[str, Json]):
    """Zero process spawns and no network: the last full status (status-snapshot.json) with `running` read fresh from the leases and the
    cached logins from auth-cache.json. `age_s` = seconds since the snapshot was taken (null when no status has run yet)."""
    t = env.now()
    st = env.load_state()
    snap: dict[str, Json] = {}
    with contextlib.suppress(OSError, ValueError):
        d = json.loads(env.snapshot_path().read_text(encoding="utf-8"))
        snap = d if isinstance(d, dict) else {}
    at = snap.get("ts")
    out = {k: v for k, v in snap.items() if k not in ("ts", "running")}
    running = running_rows(st, t)
    auth = usage.auth_cache().rows(st, t)
    age_s = int(t - at) if isinstance(at, (int, float)) else None
    book = HoldBook(st.holds)
    holds = book.rows(t)
    accounts = snap.get("accounts")
    used = (
        {n: (v.get("week") if v.get("week") is not None else v.get("five")) for n, v in accounts.items() if isinstance(v, dict)}
        if isinstance(accounts, dict)
        else {}
    )
    asks = [
        x.as_dict() for x in book.asks({n: as_num(u) for n, u in used.items()}, t)
    ]  # the stamps are the full status's: never written here
    out.update(v=1, cheap=True, ts=t, age_s=age_s, running=running, holds=holds, asks=asks, auth=auth)
    out.setdefault("accounts", {})
    cached = netprobe.load(str(env.net_cache_path()))  # a file, not a socket: cheap opens no connection
    out.update(roles=roles.refresh(snap.get("roles"), holds, cached, t), network=net.network_view(cached, t))
    print(
        json.dumps(out)
        if a.json
        else "\n".join(f"{n}: {c['ok']} ({c['age_s']}s old)" for n, c in auth.items())
        + f"\nrunning: {len(running)}  snapshot age: {age_s}s"
    )
    return 0


def full_status(cfg: dict[str, Json], claude_usage: Json = None) -> tuple[dict[str, Json], dict[str, Account], dict[str, Json]]:
    """The full status: probes the fleet, publishes the accounts, leaves the snapshot `--cheap` reads. -> (payload, accounts, cockpit)."""
    t = env.now()
    st = env.load_state()
    accounts = decide.fleet_builder(cfg).build(st, t, claude_usage).accounts
    ck = cockpit.cockpit(cfg, accounts, st, t)
    payload = status_payload(cfg, accounts, ck, st, t)
    write_snapshot(payload)
    return payload, accounts, ck


def cmd_status(a: env.Args, cfg: dict[str, Json]):
    if a.cheap:
        return cmd_status_cheap(a, cfg)
    payload, accounts, ck = full_status(cfg, decide.parse_json_arg(a.claude_usage))
    if a.json:
        print(json.dumps(payload))
        return 0
    print("\n".join(cockpit.cockpit_text(ck)))
    for n in cockpit.needs_input(accounts):
        print(f"needs input: {n['what']}: {n['how']}")
    return 0
