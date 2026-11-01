"""Durable pause policy: every known reason has either a clock wake or an owner wake.

Delegate reasons are open on the wire. Unknown ones are held for the owner, never guessed transient.
Attempt zero is the first pause; history lives in the existing Park record across retries and reason changes.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.parks import Park
from taskloop.domain.beads.park import text_hash


@dataclass(frozen=True)
class PauseRule:
    permanence: Permanence
    base_s: float = 0.0
    cap_s: float = 0.0


TABLE: Final[dict[str, PauseRule]] = {
    "no_lane": PauseRule("transient", 60, 3600),
    "only_family_unready": PauseRule("transient", 60, 3600),
    "same_family": PauseRule("transient", 60, 3600),
    "busy": PauseRule("transient", 30, 1800),
    "timeout": PauseRule("transient", 60, 3600),
    "network": PauseRule("transient", 30, 1800),
    "transient_infrastructure": PauseRule("transient", 60, 3600),
    "rate_limited": PauseRule("transient", 60, 3600),
    "hung": PauseRule("transient", 60, 3600),
    "vendor_blip": PauseRule("transient", 30, 1800),
    "worker_failed": PauseRule("transient", 60, 3600),
    "schema_invalid": PauseRule("transient", 60, 3600),
    "held": PauseRule("transient", 60, 3600),
    "duplicate_task": PauseRule("transient", 30, 1800),
    "lock": PauseRule("transient", 30, 1800),
    "crash": PauseRule("transient", 60, 3600),
    "no_answer": PauseRule("transient", 60, 3600),
    "killed": PauseRule("transient", 60, 3600),
    "engine_only_unenforced": PauseRule("needs_owner"),
    "overrun": PauseRule("needs_owner"),
    "secrets": PauseRule("needs_owner"),
    "credit_exhausted": PauseRule("needs_owner"),
    "logged_out": PauseRule("needs_owner"),
    "bad_request": PauseRule("needs_owner"),
    "caller": PauseRule("needs_owner"),
    "setup": PauseRule("needs_owner"),
    "profile_ahead": PauseRule("needs_owner"),
    "contract_violation": PauseRule("needs_owner"),
    # Engine outcomes are typed reasons when no delegate stop supplied a finer one.
    "pause_lane": PauseRule("transient", 60, 3600),
    "pause_network": PauseRule("transient", 30, 1800),
    "pause_killed": PauseRule("transient", 60, 3600),
    "pause_moved": PauseRule("transient", 60, 3600),
    "fault_infra": PauseRule("transient", 60, 3600),
    "fault_crashed": PauseRule("transient", 60, 3600),
    "fault_stale_base": PauseRule("transient", 60, 3600),
    "fault_slot": PauseRule("needs_owner"),
    "fault_denied": PauseRule("needs_owner"),
    "fault_plan": PauseRule("needs_owner"),
    "fault_land": PauseRule("needs_owner"),
    "fault_engine": PauseRule("needs_owner"),
    "fault_bad_request": PauseRule("needs_owner"),
    "fault_contract_skew": PauseRule("needs_owner"),
    "fault_base_red": PauseRule("needs_owner"),
    "ask_decision": PauseRule("needs_owner"),
    "ask_stuck": PauseRule("needs_owner"),
    "ask_budget": PauseRule("needs_owner"),
    "ask_ticket": PauseRule("needs_owner"),
    "wait_ask": PauseRule("needs_owner"),
    "owner_park": PauseRule("needs_owner"),
    "lost_run": PauseRule("transient", 60, 3600),
    "bd_push_rejected": PauseRule("needs_owner"),
    "dolt_push_rejected": PauseRule("needs_owner"),
    "forge_5xx": PauseRule("transient", 30, 1800),
}


def rule(reason: str) -> PauseRule:
    return TABLE.get(reason, PauseRule("needs_owner"))


def delay(policy: PauseRule, attempt: int, random: Callable[[], float]) -> float:
    """Cap the exponential before applying ±20% jitter; clamp exponent to avoid overflow after long outages."""
    return min(policy.base_s * 2 ** min(max(attempt, 0), 63), policy.cap_s) * (0.8 + 0.4 * random())


def after_pause(rec: Park | None, b: Bead, run: str, now: float, reason: str,
                random: Callable[[], float], not_before: float = 0.0, *, question: bool = False) -> Park:
    if rec is not None and rec.run == run:
        return rec
    policy = rule(reason)
    counts = dict(rec.attempts) if rec else {}
    attempt = counts.get(reason, 0)
    counts[reason] = attempt + 1
    retry_at = max(now + delay(policy, attempt, random), not_before) if policy.permanence == "transient" else 0.0
    h = text_hash(b)
    runs = (rec.runs + 1 if rec and rec.hash == h else 1) if question else 0
    return Park(bead=b.id, hash=h, runs=runs, run=run, t=now, reason=reason,
                permanence=policy.permanence, retry_at=retry_at, attempts=counts)
