"""The closed sets that are free strings today."""
from enum import StrEnum


class Step(StrEnum):
    RESET = "reset"
    PLAN = "plan"
    REPLAN = "replan"
    WRITE = "write"
    CHECKS = "checks"
    REVIEW = "review"
    VERIFY = "verify"
    LOOK = "look"
    GATE = "gate"
    LAND = "land"
    CLOSE = "close"
    REFLECT = "reflect"


class Outcome(StrEnum):
    LANDED = "landed"
    PARKED = "parked"
    BLOCKED = "blocked"
    FAILED = "failed"
    DONE = "done"


class WhyCode(StrEnum):
    NEEDS_HUMAN = "needs_human"
    PAUSED = "paused"
    FAILED = "failed"
    STUCK = "stuck"
    VERIFY = "verify"
    OWNER_DECISION = "owner_decision"
    OVER_BUDGET = "over_budget"
    CHECK_BEFORE_LAND = "check_before_land"
    TICKET = "ticket"
    GATE_RED = "gate_red"
    STOPPED_BY_COORDINATOR = "stopped_by_coordinator"
    LANE_OUT = "lane_out"
    NETWORK = "network"
    HUNG = "hung"
    SCHEMA_INVALID = "schema_invalid"


class Cause(StrEnum):
    LANE_OUT = "lane_out"
    LANE_WAIT = "lane_wait"
    INVALID_OUTPUT = "invalid_output"
    BAD_CHECKS = "bad_checks"
    GATE_RED = "gate_red"
    CONFLICT = "conflict"
    VERIFY_WRONG = "verify_wrong"
    PUSH_RACE = "push_race"
    PLAN_SENT_BACK = "plan_sent_back"


class AskKind(StrEnum):
    DECISION = "decision"
    VERIFY = "verify"
    STUCK = "stuck"
    DENIED = "denied"
    TICKET = "ticket"
    BUDGET = "budget"


class AskStatus(StrEnum):
    OPEN = "open"
    PARKED = "parked"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    HUNG = "hung"
    TIMEOUT = "timeout"
    CACHED = "cached"


class WaitWhat(StrEnum):
    LANE = "lane"
    NETWORK = "network"
    UNITY_SLOT = "unity_slot"
    EDITOR_LOCK = "editor_lock"
    DELEGATE_CRASH = "delegate_crash"
    LAND_LOCK = "land_lock"
    REVIEW_LOCK = "review_lock"
    AREA_LOCK = "area_lock"
    SLOT = "slot"


class LockWhat(StrEnum):
    LAND = "land"
    REVIEW = "review"
    AREA = "area"
    SLOT_TAKE = "slot_take"
    WORKTREE = "worktree"
    RELEASE = "release"


class Family(StrEnum):
    OPENAI = "openai"
    CLAUDE = "claude"
    XAI = "xai"
    DEEPSEEK = "deepseek"
    ZAI = "zai"
