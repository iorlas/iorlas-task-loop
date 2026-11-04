"""Durable pause policy: every known reason has either a clock wake or an owner wake.

Delegate reasons are open on the wire; their stop facts decide permanence, including unfamiliar reasons.
Attempt zero is the first pause; transient pauses allow three retries except network outages, which charge nothing.
Fault outcomes keep their separate history-based retry policy and do not consume pause attempts.
History lives in the existing Park record across retries and reason changes, keyed by producer:reason.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.parks import Park
from taskloop.domain.beads.park import text_hash
from taskloop.domain.lanes.pause_reasons import Producer, Reason, Unknown


@dataclass(frozen=True)
class PauseRule:
    permanence: Permanence
    base_s: float = 0.0
    cap_s: float = 0.0
    max_attempts: int = 0


@dataclass(frozen=True)
class Backoff:
    base_s: float = 60
    cap_s: float = 3600
    max_attempts: int = 3


# Engine retry budgets, not delegate classifications. Delegate callers supply stop
# permanence; without those facts there is no basis for an automatic retry.
BACKOFF: Final[dict[str, Backoff]] = {
    Reason.ONLY_FAMILY_UNREADY: Backoff(),
    Reason.BUSY: Backoff(30, 1800),
    Reason.TIMEOUT: Backoff(),
    Reason.NETWORK: Backoff(30, 1800, 0),
    Reason.RATE_LIMITED: Backoff(),
    Reason.HUNG: Backoff(),
    Reason.VENDOR_BLIP: Backoff(30, 1800),
    Reason.WORKER_FAILED: Backoff(),
    Reason.SCHEMA_INVALID: Backoff(),
    Reason.HELD: Backoff(),
    Reason.DUPLICATE_TASK: Backoff(30, 1800),
    Reason.LOCK: Backoff(30, 1800),
    Reason.KILLED: Backoff(),
}

# Released engine policy wins even when a delegate supplies transient retry hints.
OVERRIDES: Final[dict[str, tuple[Permanence, str]]] = {
    Reason.NO_LANE: ("needs_owner", "The owner must restore an available lane; a predicted time cannot repair it."),
    Reason.CRASH: ("needs_owner", "A delegate crash needs owner investigation after in-process retries are exhausted."),
}


MACHINE_FIXED: Final[frozenset[Reason]] = frozenset({
    Reason.NO_LANE,  # The owner restores an available lane.
    Reason.LOGGED_OUT,  # The owner renews the lane's login.
    Reason.CREDIT_EXHAUSTED,  # The owner replenishes the account's credit.
    Reason.SECRETS,  # The owner supplies the machine's missing credentials.
    Reason.SETUP,  # The owner repairs the delegate installation or configuration.
    Reason.CONTRACT_VIOLATION,  # The owner restores compatible engine and delegate contracts.
    Reason.ENGINE_ONLY_UNENFORCED,  # The owner fixes enforcement of engine-only commands.
})


TABLE: Final[dict[tuple[Producer, str], PauseRule]] = {
    # Locally synthesized delegate reasons absent from delegate's recorded contract.
    ("delegate", Reason.ONLY_FAMILY_UNREADY): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.ENGINE_ONLY_UNENFORCED): PauseRule("needs_owner"),
    ("engine", Reason.SAME_FAMILY): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.ENGINE_CRASH): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.STAGE_REFUSED): PauseRule("needs_owner"),
    ("engine", Reason.TRANSIENT_INFRASTRUCTURE): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.NO_ANSWER): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.OVERRUN): PauseRule("needs_owner"),
    ("engine", Reason.PROFILE_AHEAD): PauseRule("needs_owner"),
    ("engine", Reason.SETUP_OWN_TREE): PauseRule("needs_owner"),
    ("engine", Reason.CONTRACT_VIOLATION): PauseRule("needs_owner"),
    ("engine", Reason.PAUSE_LANE): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.PAUSE_NETWORK): PauseRule("transient", 30, 1800),
    ("engine", Reason.PAUSE_KILLED): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.PAUSE_MOVED): PauseRule("transient", 60, 3600, 3),
    # Fault retries are charged by outcome.apply, not the durable pause budget.
    ("engine", Reason.FAULT_INFRA): PauseRule("transient", 60, 3600),
    ("engine", Reason.FAULT_CRASHED): PauseRule("transient", 60, 3600),
    ("engine", Reason.FAULT_STALE_BASE): PauseRule("transient", 60, 3600),
    ("engine", Reason.FAULT_SLOT): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_DENIED): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_PLAN): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_LAND): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_ENGINE): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_BAD_REQUEST): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_CONTRACT_SKEW): PauseRule("needs_owner"),
    ("engine", Reason.FAULT_BASE_RED): PauseRule("needs_owner"),
    ("engine", Reason.ASK_DECISION): PauseRule("needs_owner"),
    ("engine", Reason.ASK_STUCK): PauseRule("needs_owner"),
    ("engine", Reason.ASK_BUDGET): PauseRule("needs_owner"),
    ("engine", Reason.ASK_TICKET): PauseRule("needs_owner"),
    ("engine", Reason.WAIT_ASK): PauseRule("needs_owner"),
    ("engine", Reason.OWNER_PARK): PauseRule("needs_owner"),
    ("engine", Reason.PLAN_NOOP): PauseRule("needs_owner"),
    ("engine", Reason.LOST_RUN): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.BD_PUSH_REJECTED): PauseRule("needs_owner"),
    ("engine", Reason.DOLT_PUSH_REJECTED): PauseRule("needs_owner"),
    ("engine", Reason.FORGE_5XX): PauseRule("transient", 30, 1800, 3),
}


def producer_of(reason: str) -> Producer:
    return "engine" if ("engine", reason) in TABLE else "delegate"


def attempt_key(reason: str, producer: Producer | None = None) -> str:
    return f"{producer or producer_of(reason)}:{reason}"


def rule(reason: str | Unknown, producer: Producer | None = None, permanence: Permanence | None = None) -> PauseRule:
    raw = reason if isinstance(reason, str) else reason.raw
    producer = producer or producer_of(raw)
    policy = TABLE.get((producer, raw)) if isinstance(reason, str) else None
    if policy is not None:
        return policy
    if producer == "engine":
        return PauseRule("needs_owner")
    backoff = BACKOFF.get(raw) if isinstance(reason, str) else None
    permanence = OVERRIDES[raw][0] if raw in OVERRIDES else permanence or "needs_owner"
    if permanence == "needs_owner":
        return PauseRule(permanence)
    backoff = backoff or Backoff()
    return PauseRule(permanence, backoff.base_s, backoff.cap_s, backoff.max_attempts)


def history(rec: Park | None) -> dict[str, int]:
    """Qualify legacy counters without resetting their retry budgets on upgrade."""
    counts: dict[str, int] = {}
    for key, count in (rec.attempts if rec is not None else {}).items():
        qualified = key if ":" in key else attempt_key(key)
        counts[qualified] = max(counts.get(qualified, 0), count)
    return counts


def delay(policy: PauseRule, attempt: int, random: Callable[[], float]) -> float:
    """Cap the exponential before applying ±20% jitter; clamp exponent to avoid overflow after long outages."""
    return min(policy.base_s * 2 ** min(max(attempt, 0), 63), policy.cap_s) * (0.8 + 0.4 * random())


def exhausted(policy: PauseRule, rec: Park | None, reason: str, attempt: int, fingerprint: str) -> bool:
    if policy.max_attempts and attempt >= policy.max_attempts:
        return True
    return (reason == "engine_crash" and rec is not None and rec.reason == reason
            and bool(fingerprint) and rec.fingerprint == fingerprint)


def after_pause(rec: Park | None, b: Bead, run: str, now: float, reason: str,
                random: Callable[[], float], not_before: float = 0.0, *, question: bool = False, fingerprint: str = "",
                producer: Producer | None = None, permanence: Permanence | None = None) -> Park:
    if rec is not None and rec.run == run:
        return rec
    producer = producer or producer_of(reason)
    policy = rule(reason, producer, permanence)
    counts = history(rec)
    key = attempt_key(reason, producer)
    attempt = counts.get(key, 0)
    if (producer, reason) in (("delegate", "network"), ("engine", "pause_network")):
        attempt = 0  # outages never consume a bead's attempts; only the loop's probe gates recovery
    else:
        counts[key] = attempt + 1
    fingerprint = fingerprint if producer == "engine" else ""
    wake_permanence: Permanence = "needs_owner" if exhausted(policy, rec, reason, attempt, fingerprint) else policy.permanence
    retry_at = max(now + delay(policy, attempt, random), not_before) if wake_permanence == "transient" else 0.0
    h = text_hash(b)
    runs = (rec.runs + 1 if rec is not None and rec.hash == h else 1) if question else 0
    return Park(bead=b.id, hash=h, runs=runs, run=run, t=now, reason=reason,
                permanence=wake_permanence, retry_at=retry_at, attempts=counts, fingerprint=fingerprint)
