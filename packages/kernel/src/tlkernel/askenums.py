"""The ask owner's vocabulary."""
from enum import StrEnum


class AskKind(StrEnum):
    DECISION = "decision"
    STUCK = "stuck"
    TICKET = "ticket"
    BUDGET = "budget"


class AskClass(StrEnum):
    """Why the engine cannot go on without the owner. The first ten are owner matters; the last five are the engine's own
    trouble and never become an ask (lint refuses them)."""
    OPEN_QUESTION = "open_question"
    EXTERNAL_FACT = "external_fact"
    UNPROVEN = "unproven"
    NO_PROGRESS = "no_progress"
    CAP_REACHED = "cap_reached"
    OVER_BUDGET = "over_budget"
    MISSING_CRITERIA = "missing_criteria"
    TOO_BIG = "too_big"
    PR_OPEN = "pr_open"
    PR_CLOSED = "pr_closed"
    LANE_FAILURE = "lane_failure"
    BAD_REQUEST = "bad_request"
    SANDBOX_DENIAL = "sandbox_denial"
    STALE_BASE = "stale_base"
    MISSING_TOOL = "missing_tool"


class AskStatus(StrEnum):
    OPEN = "open"
    PARKED = "parked"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"
