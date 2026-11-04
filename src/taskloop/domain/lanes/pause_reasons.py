"""Pause identities belong to their producer; unfamiliar wire values keep their raw spelling."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

Producer = Literal["delegate", "engine"]


class Reason(StrEnum):
    NO_LANE = "no_lane"
    ONLY_FAMILY_UNREADY = "only_family_unready"
    SAME_FAMILY = "same_family"
    BUSY = "busy"
    TIMEOUT = "timeout"
    NETWORK = "network"
    ENGINE_CRASH = "engine_crash"
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
    PAUSE_LANE = "pause_lane"
    PAUSE_NETWORK = "pause_network"
    PAUSE_KILLED = "pause_killed"
    PAUSE_MOVED = "pause_moved"
    FAULT_INFRA = "fault_infra"
    FAULT_CRASHED = "fault_crashed"
    FAULT_STALE_BASE = "fault_stale_base"
    FAULT_SLOT = "fault_slot"
    FAULT_DENIED = "fault_denied"
    FAULT_PLAN = "fault_plan"
    FAULT_LAND = "fault_land"
    FAULT_ENGINE = "fault_engine"
    FAULT_BAD_REQUEST = "fault_bad_request"
    FAULT_CONTRACT_SKEW = "fault_contract_skew"
    FAULT_BASE_RED = "fault_base_red"
    ASK_DECISION = "ask_decision"
    ASK_STUCK = "ask_stuck"
    ASK_BUDGET = "ask_budget"
    ASK_TICKET = "ask_ticket"
    WAIT_ASK = "wait_ask"
    OWNER_PARK = "owner_park"
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
