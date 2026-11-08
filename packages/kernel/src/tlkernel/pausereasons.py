"""Pause identities belong to their producer; unfamiliar wire values keep their raw spelling."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from tlkernel.kinds import Kind

Producer = Literal["delegate", "engine"]


class Reason(StrEnum):
    NO_ACCOUNT = "no_account"
    ONLY_FAMILY_UNREADY = "only_family_unready"
    LOOP_EXCLUDED = "loop_excluded"
    SAME_FAMILY = "same_family"
    BUSY = "busy"
    TIMEOUT = "timeout"
    NETWORK = "network"
    ENGINE_CRASH = Kind.ENGINE_CRASH.value
    STAGE_REFUSED = "stage_refused"
    TRANSIENT_INFRASTRUCTURE = "transient_infrastructure"
    RATE_LIMITED = "rate_limited"
    HUNG = "hung"
    VENDOR_BLIP = "vendor_blip"
    WORKER_FAILED = "worker_failed"
    SCHEMA_INVALID = "schema_invalid"
    HELD = "held"
    DUPLICATE_TASK = "duplicate_task"
    LOCK = "lock"
    CRASH = "crash"
    NO_ANSWER = "no_answer"
    KILLED = "killed"
    WORKER_SURVIVED = "worker_survived"
    ENGINE_ONLY_UNENFORCED = "engine_only_unenforced"
    OVERRUN = "overrun"
    SECRETS = "secrets"
    CREDIT_EXHAUSTED = "credit_exhausted"
    LOGGED_OUT = "logged_out"
    BAD_REQUEST = "bad_request"
    CALLER = "caller"
    SETUP = "setup"
    PROFILE_AHEAD = "profile_ahead"
    SETUP_OWN_TREE = "setup_own_tree"
    CONTRACT_VIOLATION = "contract_violation"
    PAUSE_ACCOUNT = Kind.PAUSE_ACCOUNT.value
    PAUSE_NETWORK = Kind.PAUSE_NETWORK.value
    PAUSE_KILLED = Kind.PAUSE_KILLED.value
    PAUSE_MOVED = Kind.PAUSE_MOVED.value
    FAULT_INFRA = Kind.FAULT_INFRA.value
    FAULT_CRASHED = Kind.FAULT_CRASHED.value
    FAULT_STALE_BASE = Kind.FAULT_STALE_BASE.value
    FAULT_SLOT = Kind.FAULT_SLOT.value
    FAULT_DENIED = Kind.FAULT_DENIED.value
    FAULT_PLAN = Kind.FAULT_PLAN.value
    FAULT_LAND = Kind.FAULT_LAND.value
    FAULT_ENGINE = Kind.FAULT_ENGINE.value
    FAULT_BAD_REQUEST = Kind.FAULT_BAD_REQUEST.value
    FAULT_CONTRACT_SKEW = Kind.FAULT_CONTRACT_SKEW.value
    FAULT_BASE_RED = Kind.FAULT_BASE_RED.value
    ASK_DECISION = Kind.ASK_DECISION.value
    ASK_STUCK = Kind.ASK_STUCK.value
    ASK_BUDGET = Kind.ASK_BUDGET.value
    ASK_TICKET = Kind.ASK_TICKET.value
    WAIT_ASK = Kind.WAIT_ASK.value
    OWNER_PARK = Kind.OWNER_PARK.value
    PLAN_NOOP = "plan_noop"
    LOST_RUN = "lost_run"
    BD_PUSH_REJECTED = "bd_push_rejected"
    DOLT_PUSH_REJECTED = "dolt_push_rejected"
    FORGE_5XX = "forge_5xx"


@dataclass(frozen=True)
class Unknown:
    raw: str


def parse(raw: str) -> Reason | Unknown:
    try:
        return Reason(raw)
    except ValueError:
        return Unknown(raw)
