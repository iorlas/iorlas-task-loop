"""`state.json`: everything the router remembers between calls, one typed document (`v` 2).

Sections have one owner each (see domain/): `out` the OutBoard, `holds` the HoldBook, `leases` the LeaseBook, `prev` the DwellMemory,
`auth` the one login cache (the old auth-cache.json is merged in), `codex_limits` / `claude_usage` the usage readers' caches. Every write
goes through `StateStore.transaction()` under one lock. A file of another shape reads as an empty document: nothing is migrated.
"""

from dataclasses import field

from delegate.contracts.codec import mutable
from delegate.contracts.json_types import Json

V = 2


@mutable
class OutState:
    """A account marked out. source: vendor (the vendor stated the end) | guess | manual; `set` is the wall clock of the write (running
    workers read it)."""

    until: float
    why: str = "reported out"
    at: float = 0.0
    set: float = 0.0
    reason: str = "limit"
    source: str = "guess"
    zone: str | None = None
    guess_n: int = 0


@mutable
class Hold:
    id: str
    account: str
    until: float
    set_at: float
    roles: list[str] = field(default_factory=list)  # empty: every role
    set_by: str = "owner"
    reason: str = ""
    stale_at: float | None = None


@mutable
class Lease:
    """A running `run`: renewed while its route.py lives; an expired one is dropped unless its process still runs."""

    account: str
    pid: int
    start: float
    expires: float
    pid_start: str | None = None
    role: str | None = None
    task: str = ""
    silence_s: float | None = None
    canary: str | None = None
    worker_pid: int | None = None
    worker_start: str | None = None
    last_event: float | None = None
    ref: str | None = None


@mutable
class RefRecord:
    """What a vendor session id was started with, for `--resume`."""

    account: str
    model: str
    effort: str
    mode: str
    cap: float | None = None
    rung: int | None = None
    fallback: bool | None = None
    fallback_reason: str | None = None
    first_account: str | None = None


@mutable
class ThreadRecord:
    ref: str
    account: str | None
    model: str | None
    context_k: float | None = None
    fallback: bool = False
    first_account: str | None = None


@mutable
class Dwell:
    account: str
    since: float


@mutable
class AuthEntry:
    at: float
    ok: bool
    why: str = ""


@mutable
class UsageCache:
    at: float
    data: Json = None


@mutable
class StateDoc:
    V = V
    out: dict[str, OutState] = field(default_factory=dict)
    leases: dict[str, Lease] = field(default_factory=dict)
    refs: dict[str, RefRecord] = field(default_factory=dict)
    threads: dict[str, ThreadRecord] = field(default_factory=dict)
    holds: dict[str, Hold] = field(default_factory=dict)
    prev: dict[str, Dwell] = field(default_factory=dict)
    auth: dict[str, AuthEntry] = field(default_factory=dict)
    warned_at: dict[str, float] = field(default_factory=dict)
    codex_limits: UsageCache | None = None
    claude_usage: UsageCache | None = None


# State keys and accounts an older state.json may still carry. Loading drops them with one warning each; any other unknown key resets the
# file.
RETIRED_STATE = ("codex_login_pid",)
RETIRED_ACCOUNTS = ("CLAUDE_CREDIT",)


def split_retired_state(data: dict[str, Json]) -> tuple[dict[str, Json], list[str]]:
    """(data without retired top-level keys and without entries of a retired account, what was dropped as 'key' or 'section.entry', in file
    order).
    A per-account entry is one keyed by the account or carrying `account`; every other entry, and the input, are untouched."""
    gone: list[str] = []
    out: dict[str, Json] = {}
    for k, v in data.items():
        if k in RETIRED_STATE:
            gone.append(k)
        elif isinstance(v, dict) and k in ("out", "holds", "leases", "refs", "threads", "prev", "auth", "warned_at"):
            keep: dict[str, Json] = {}
            for name, e in v.items():
                if name in RETIRED_ACCOUNTS or (isinstance(e, dict) and e.get("account") in RETIRED_ACCOUNTS):
                    gone.append(f"{k}.{name}")
                else:
                    keep[name] = e
            out[k] = keep
        else:
            out[k] = v
    return out, gone


@mutable
class Profile:
    """The owner's account choices, `config.json` `profile`: never a setting, never merged into one."""

    accounts: dict[str, str] = field(default_factory=dict)  # account -> enabled | declined; an account not listed is undecided
    ack: list[str] = field(default_factory=list)
    offered: list[str] = field(default_factory=list)  # accounts seen not usable for the first time, reported once
