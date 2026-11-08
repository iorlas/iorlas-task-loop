"""FleetBuilder: every `Account` for one call. Gathers what the router needs and nothing else: the account profile (which accounts this
machine
uses), a usage reading per account, the out board, the health fold and the leases. Side effects go through the injected stores and readers.

`mark_busy`, `settle_holds` and `drift_warnings` are the three things a call does to the fleet before the Router sees it.
"""

import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from any_breaker import State

from delegate.contracts.json_types import Json
from delegate.contracts.routing import AccountSpec, ModelSpec, Routing, Settings
from delegate.contracts.state import AuthEntry, StateDoc
from delegate.contracts.stores import CheckpointStore, ConfigStore, HistoryStore, StateStore
from delegate.domain.accounts.account import Account
from delegate.domain.accounts.leases import LeaseBook
from delegate.domain.health.ledger import HealthLedger
from delegate.domain.holds.book import HoldBook, StaleHold

Reader = Callable[
    [Account, Settings, StateDoc, float, Json], None
]  # fills an account's usage in place (the claude reader takes the caller's get_usage)
DRIFT_NOTE = "enabled but not ready"
WARN_EVERY_S = 86400


@dataclass
class Fleet:
    accounts: dict[str, Account]
    offers: list[str] = field(default_factory=list)  # accounts seen for the first time and not usable: reported once, then remembered
    enables: list[str] = field(default_factory=list)  # undecided accounts this machine has ready: only `run` turns them on in the profile


class FleetBuilder:
    def __init__(
        self,
        routing: Routing,
        states: StateStore,
        history: HistoryStore,
        checkpoints: CheckpointStore,
        config: ConfigStore,
        readers: Mapping[str, Reader],
        configured: Callable[[], dict[str, bool]],
    ) -> None:
        self.r, self.states, self.history, self.checkpoints, self.config = routing, states, history, checkpoints, config
        self.readers, self.configured = readers, configured

    def build(self, doc: StateDoc, t: float, usage: Json = None, check_config: bool = True) -> Fleet:
        s = self.r.settings
        fleet = Fleet({})
        conf = self.configured() if check_config else {}
        health = self._health(t)
        profile = self.config.profile()
        for name, spec in self.r.accounts.items():
            if spec.opt_in and profile.accounts.get(name) != "enabled":
                continue
            mode = self._mode(name, spec, conf.get(name, True), fleet) if check_config else "on"
            if mode == "off":
                continue
            account = Account(name, spec.family, spec.kind, spec.shared_with_orchestrator)
            self.readers[spec.reader](account, s, doc, t, usage)
            self._apply_out(account, doc, t)
            if mode == "drift":
                account.out, account.out_until, account.out_reason = True, None, "logged_out"
                account.notes.insert(0, DRIFT_NOTE + " (login or key gone?)")
            apply_health(account, self.r.models, HealthLedger(s.breaker), health, t)
            fleet.accounts[name] = account
        return fleet

    def _mode(self, name: str, spec: AccountSpec, ready: bool, fleet: Fleet) -> str:
        """-> "on" | "off" | "drift". Shared accounts are always on. Otherwise the profile decides; an account never decided is on for
        this call if
        the machine has it ready (listed in `Fleet.enables`: the caller decides whether to write it), else left out silently."""
        if spec.shared_with_orchestrator:
            return "on"
        prof = self.config.profile()
        v = prof.accounts.get(name)
        if v == "declined":
            return "off"
        if v == "enabled":
            return "on" if ready else "drift"
        if ready:
            if name not in fleet.enables:
                fleet.enables.append(name)
            return "on"
        if name not in prof.offered and name not in fleet.offers:
            fleet.offers.append(name)
        return "off"

    def _apply_out(self, account: Account, doc: StateDoc, t: float) -> None:
        o = doc.out.get(account.name)
        if (
            o
            and o.reason == "limit"
            and account.read_at
            and account.read_at > o.at
            and not account.out
            and (account.five or 0) < 95
            and (account.week or 0) < 95
        ):
            self.states.update(
                lambda s: s.out.pop(account.name, None)
            )  # a reading after the refusal shows room: the out was wrong or is over
            o = None
        if o and o.until > t and not account.out:  # an out reported by the model or by a launcher
            account.out, account.out_until, account.out_reason = True, o.until, o.reason
            account.notes.append(o.why)

    def _health(self, t: float) -> State:
        """The health fold over history.jsonl, continued from a cached checkpoint (a cache: no file, a damaged one or another policy = a
        full fold)."""
        pol = self.r.settings.breaker
        base = self.checkpoints.load(pol)
        rows = self.history.rows(base.ts if base else 0.0)
        state = HealthLedger(pol).fold(rows, base)
        if rows:
            self.checkpoints.save(state, pol)
        return state


def apply_health(account: Account, models: Mapping[str, ModelSpec], ledger: HealthLedger, state: State, t: float) -> None:
    """Put the breaker's view of each (account, model) pair on the account: `benched` (refused), `canary` (the next launch is the probe),
    `hview`."""
    for model, m in models.items():
        if m.family != account.family:
            continue
        v = ledger.view(state, account.name, model, t)
        account.hview[model] = v
        if v.state == "broken":
            account.benched[model] = v
        elif v.canary:
            account.canary[model] = True


def mark_busy(accounts: dict[str, Account], doc: StateDoc, s: Settings, t: float, jitter: Callable[[], int]) -> dict[str, Account]:
    """A account with all its slots taken is skipped like a refused account (a copy that is out); `jitter` keeps retrying engines from
    arriving
    together."""
    book = LeaseBook(doc.leases)
    out: dict[str, Account] = {}
    for name, account in accounts.items():
        cap, running = account.slots(s), book.running(name, t)
        out[name] = account.with_busy(t + jitter(), running, cap) if cap is not None and running >= cap and not account.out else account
    return out


def settle_holds(states: StateStore, accounts: dict[str, Account], doc: StateDoc, t: float) -> tuple[list[StaleHold], StateDoc]:
    """A hold in force whose account shows less than HOLD_STALE_BELOW % used is stale: it gets ONE ask, stamped on the record (`stale_at`)
    so
    no
    later call raises it again. -> (the asks, the state after)."""
    used = {n: account.week if account.week is not None else account.five for n, account in accounts.items()}
    stamp = HoldBook(doc.holds).to_stamp(used, t)
    if stamp:

        def apply(s: StateDoc) -> None:
            for k in stamp:
                h = s.holds.get(k)
                if h and not h.stale_at:
                    h.stale_at = t

        doc = states.update(apply)
    return HoldBook(doc.holds).asks(used, t), doc


def drift_warnings(states: StateStore, accounts: dict[str, Account], doc: StateDoc, t: float) -> list[str]:
    """A account the profile enabled but the machine no longer supports: say so once a day."""
    bad = [n for n, account in accounts.items() if account.notes and account.notes[0].startswith(DRIFT_NOTE)]
    out = [f"{n} is enabled but not ready, so it is skipped (route.py doctor)" for n in bad if t - doc.warned_at.get(n, 0) > WARN_EVERY_S]
    if out:
        states.update(lambda s: s.warned_at.update(dict.fromkeys(bad, t)))
    return out


class AuthCache:
    """The one login cache (state.json `auth`): a login probe spawns a CLI, so its answer is kept. Readers pass the age they accept."""

    def __init__(self, states: StateStore, use: bool = True) -> None:
        self.states, self.use = states, use

    def fresh(self, name: str, t: float, ttl: float, doc: StateDoc | None = None) -> AuthEntry | None:
        e = (doc or self.states.load()).auth.get(name)
        return e if self.use and e and 0 <= t - e.at <= ttl else None

    def remember(self, name: str, ok: bool | None, why: str, t: float) -> None:
        """Never fails the caller; an unknown answer (None) is not remembered."""
        if ok is not None:
            with contextlib.suppress(Exception):
                self.states.update(lambda s: s.auth.__setitem__(name, AuthEntry(at=t, ok=ok, why=why[:120])))

    def rows(self, doc: StateDoc, t: float) -> dict[str, dict[str, Json]]:
        return {n: {"ok": e.ok, "why": e.why, "age_s": int(t - e.at)} for n, e in doc.auth.items()}
