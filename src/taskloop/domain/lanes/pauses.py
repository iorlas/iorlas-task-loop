"""Durable pause policy: every known reason has either a clock wake or an owner wake.

Delegate reasons are open on the wire. Unknown ones are held for the owner, never guessed transient.
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
from taskloop.domain.lanes.pause_reasons import Producer, Reason, Unknown, parse


@dataclass(frozen=True)
class PauseRule:
    permanence: Permanence
    base_s: float = 0.0
    cap_s: float = 0.0
    max_attempts: int = 0


TABLE: Final[dict[tuple[Producer, Reason], PauseRule]] = {
    ("delegate", Reason.NO_LANE): PauseRule("needs_owner"),
    ("delegate", Reason.ONLY_FAMILY_UNREADY): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.SAME_FAMILY): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.BUSY): PauseRule("transient", 30, 1800, 3),
    ("delegate", Reason.TIMEOUT): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.NETWORK): PauseRule("transient", 30, 1800),
    ("engine", Reason.ENGINE_CRASH): PauseRule("transient", 60, 3600, 3),
    ("engine", Reason.STAGE_REFUSED): PauseRule("needs_owner"),
    ("engine", Reason.TRANSIENT_INFRASTRUCTURE): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.RATE_LIMITED): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.HUNG): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.VENDOR_BLIP): PauseRule("transient", 30, 1800, 3),
    ("delegate", Reason.WORKER_FAILED): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.SCHEMA_INVALID): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.HELD): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.DUPLICATE_TASK): PauseRule("transient", 30, 1800, 3),
    ("delegate", Reason.LOCK): PauseRule("transient", 30, 1800, 3),
    ("delegate", Reason.CRASH): PauseRule("needs_owner"),
    ("engine", Reason.NO_ANSWER): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.KILLED): PauseRule("transient", 60, 3600, 3),
    ("delegate", Reason.ENGINE_ONLY_UNENFORCED): PauseRule("needs_owner"),
    ("engine", Reason.OVERRUN): PauseRule("needs_owner"),
    ("delegate", Reason.SECRETS): PauseRule("needs_owner"),
    ("delegate", Reason.CREDIT_EXHAUSTED): PauseRule("needs_owner"),
    ("delegate", Reason.LOGGED_OUT): PauseRule("needs_owner"),
    ("delegate", Reason.BAD_REQUEST): PauseRule("needs_owner"),
    ("delegate", Reason.CALLER): PauseRule("needs_owner"),
    ("delegate", Reason.SETUP): PauseRule("needs_owner"),
    ("engine", Reason.PROFILE_AHEAD): PauseRule("needs_owner"),
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


def rule(reason: str | Unknown, producer: Producer | None = None) -> PauseRule:
    known = parse(reason) if isinstance(reason, str) else reason
    if isinstance(known, Unknown):
        return PauseRule("needs_owner")
    return TABLE.get((producer or producer_of(known), known), PauseRule("needs_owner"))


def history(rec: Park | None) -> dict[str, int]:
    """Qualify legacy counters without resetting their retry budgets on upgrade."""
    counts: dict[str, int] = {}
    for key, count in (rec.attempts if rec else {}).items():
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
                producer: Producer | None = None) -> Park:
    if rec is not None and rec.run == run:
        return rec
    producer = producer or producer_of(reason)
    policy = rule(reason, producer)
    counts = history(rec)
    key = attempt_key(reason, producer)
    attempt = counts.get(key, 0)
    if (producer, reason) in (("delegate", "network"), ("engine", "pause_network")):
        attempt = 0  # outages never consume a bead's attempts; only the loop's probe gates recovery
    else:
        counts[key] = attempt + 1
    fingerprint = fingerprint if producer == "engine" else ""
    permanence: Permanence = "needs_owner" if exhausted(policy, rec, reason, attempt, fingerprint) else policy.permanence
    retry_at = max(now + delay(policy, attempt, random), not_before) if permanence == "transient" else 0.0
    h = text_hash(b)
    runs = (rec.runs + 1 if rec and rec.hash == h else 1) if question else 0
    return Park(bead=b.id, hash=h, runs=runs, run=run, t=now, reason=reason,
                permanence=permanence, retry_at=retry_at, attempts=counts, fingerprint=fingerprint)
