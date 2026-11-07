"""Durable pause policy: every known reason has either a clock wake or an owner wake.

Delegate reasons are open on the wire; their stop facts decide permanence, including unfamiliar reasons.
Attempt zero is the first pause; transient pauses allow three retries except network outages, which charge nothing.
Fault outcomes keep their separate history-based retry policy and do not consume pause attempts.
History lives in the existing Park record across retries and reason changes, keyed by producer:reason.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from any_failure_fp import backoff

from tlkernel.bead import Bead
from tlkernel.beadpark import text_hash
from tlkernel.delegate import Permanence
from tlkernel.kinds import Kind
from tlkernel.parks import Park
from tlkernel.pausereasons import Producer, Reason, Unknown


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
BACKOFF: Final[dict[str, Backoff | None]] = {
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
    Reason.WORKER_SURVIVED: None,
    Reason.NO_LANE: None, Reason.LOOP_EXCLUDED: None, Reason.SAME_FAMILY: None, Reason.ENGINE_CRASH: None, Reason.STAGE_REFUSED: None,
    Reason.TRANSIENT_INFRASTRUCTURE: None, Reason.CRASH: None, Reason.NO_ANSWER: None, Reason.ENGINE_ONLY_UNENFORCED: None,
    Reason.OVERRUN: None, Reason.SECRETS: None, Reason.CREDIT_EXHAUSTED: None, Reason.LOGGED_OUT: None,
    Reason.BAD_REQUEST: None, Reason.CALLER: None, Reason.SETUP: None, Reason.SETUP_OWN_TREE: None,
    Reason.PROFILE_AHEAD: None, Reason.CONTRACT_VIOLATION: None,
    Reason.PAUSE_LANE: None, Reason.PAUSE_NETWORK: None, Reason.PAUSE_KILLED: None, Reason.PAUSE_MOVED: None,
    Reason.FAULT_INFRA: None, Reason.FAULT_CRASHED: None, Reason.FAULT_STALE_BASE: None, Reason.FAULT_SLOT: None,
    Reason.FAULT_DENIED: None, Reason.FAULT_PLAN: None, Reason.FAULT_LAND: None, Reason.FAULT_ENGINE: None,
    Reason.FAULT_BAD_REQUEST: None, Reason.FAULT_CONTRACT_SKEW: None, Reason.FAULT_BASE_RED: None,
    Reason.ASK_DECISION: None, Reason.ASK_STUCK: None, Reason.ASK_BUDGET: None, Reason.ASK_TICKET: None,
    Reason.WAIT_ASK: None, Reason.OWNER_PARK: None, Reason.PLAN_NOOP: None, Reason.LOST_RUN: None,
    Reason.BD_PUSH_REJECTED: None, Reason.DOLT_PUSH_REJECTED: None, Reason.FORGE_5XX: None,
}

# Released engine policy wins even when a delegate supplies transient retry hints.
OVERRIDES: Final[dict[str, tuple[Permanence, str] | None]] = {
    Reason.NO_LANE: ("needs_owner", "The owner must restore an available lane; a predicted time cannot repair it."),
    Reason.CRASH: ("needs_owner", "A delegate crash needs owner investigation after in-process retries are exhausted."),
    Reason.ONLY_FAMILY_UNREADY: None, Reason.LOOP_EXCLUDED: None, Reason.SAME_FAMILY: None, Reason.BUSY: None, Reason.TIMEOUT: None,
    Reason.NETWORK: None,
    Reason.ENGINE_CRASH: None, Reason.STAGE_REFUSED: None, Reason.TRANSIENT_INFRASTRUCTURE: None,
    Reason.RATE_LIMITED: None, Reason.HUNG: None, Reason.VENDOR_BLIP: None, Reason.WORKER_FAILED: None,
    Reason.SCHEMA_INVALID: None, Reason.HELD: None, Reason.DUPLICATE_TASK: None, Reason.LOCK: None, Reason.NO_ANSWER: None,
    Reason.KILLED: None, Reason.WORKER_SURVIVED: None, Reason.ENGINE_ONLY_UNENFORCED: None, Reason.OVERRUN: None, Reason.SECRETS: None,
    Reason.CREDIT_EXHAUSTED: None, Reason.LOGGED_OUT: None, Reason.BAD_REQUEST: None, Reason.CALLER: None,
    Reason.SETUP: None, Reason.SETUP_OWN_TREE: None, Reason.PROFILE_AHEAD: None, Reason.CONTRACT_VIOLATION: None,
    Reason.PAUSE_LANE: None, Reason.PAUSE_NETWORK: None, Reason.PAUSE_KILLED: None, Reason.PAUSE_MOVED: None,
    Reason.FAULT_INFRA: None, Reason.FAULT_CRASHED: None, Reason.FAULT_STALE_BASE: None, Reason.FAULT_SLOT: None,
    Reason.FAULT_DENIED: None, Reason.FAULT_PLAN: None, Reason.FAULT_LAND: None, Reason.FAULT_ENGINE: None,
    Reason.FAULT_BAD_REQUEST: None, Reason.FAULT_CONTRACT_SKEW: None, Reason.FAULT_BASE_RED: None,
    Reason.ASK_DECISION: None, Reason.ASK_STUCK: None, Reason.ASK_BUDGET: None, Reason.ASK_TICKET: None,
    Reason.WAIT_ASK: None, Reason.OWNER_PARK: None, Reason.PLAN_NOOP: None, Reason.LOST_RUN: None,
    Reason.BD_PUSH_REJECTED: None, Reason.DOLT_PUSH_REJECTED: None, Reason.FORGE_5XX: None,
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
    override = OVERRIDES.get(raw)
    permanence = override[0] if override is not None else permanence or "needs_owner"
    if permanence == "needs_owner":
        return PauseRule(permanence)
    backoff = backoff or Backoff()
    return PauseRule(permanence, backoff.base_s, backoff.cap_s, backoff.max_attempts)


def history(rec: Park | None) -> dict[str, int]:
    """The attempts counted so far, by producer:reason."""
    return dict(rec.attempts) if rec is not None else {}


def delay(policy: PauseRule, attempt: int, random: Callable[[], float]) -> float:
    return backoff(policy.base_s, policy.cap_s, attempt, random)


def exhausted(policy: PauseRule, rec: Park | None, reason: str, attempt: int, fingerprint: str) -> bool:
    if policy.max_attempts and attempt >= policy.max_attempts:
        return True
    return (reason == Kind.ENGINE_CRASH.value and rec is not None and rec.reason == reason
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
    if (producer, reason) in (("delegate", "network"), ("engine", Kind.PAUSE_NETWORK.value)):
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
