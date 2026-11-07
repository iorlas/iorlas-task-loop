"""Shared dashboard display and owner-action enums."""
from enum import StrEnum


class Column(StrEnum):
    """Board column, derived from engine state (dash-spec §3); a card is never dragged."""

    BACKLOG = "backlog"
    WORKING = "working"
    QUESTIONS = "questions"
    REVIEW = "review"
    LOOK = "look"
    LANDING = "landing"
    DONE = "done"


class Marker(StrEnum):
    """The one state mark of a bead (dash-spec §2.4)."""

    RUN = "run"
    ASK = "ask"
    LOOK = "look"
    SOFT_ASK = "soft_ask"
    PARKED = "parked"
    NOOP = "noop"
    READY = "ready"
    BLOCKED = "blocked"
    DONE = "done"
    STUCK = "stuck"
    EXITED = "exited"


class Phase(StrEnum):
    """The six phases the page draws (dash-spec calls them stages; three `Stage` records already exist).

    Engine steps map onto them: plan+replan -> plan, write -> write, checks -> test,
    review+verify -> review, look -> look, gate+land -> land; reset, close and reflect are not drawn."""

    PLAN = "plan"
    WRITE = "write"
    TEST = "test"
    REVIEW = "review"
    LOOK = "look"
    LAND = "land"


class OwnerCause(StrEnum):
    """Why an agent asked or a run stopped: one list for asks and stops (dash-spec §5.2). Not the engine's transition `Cause`."""

    REQUIREMENT = "requirement"
    DECISION = "decision"
    ENVIRONMENT = "environment"
    PROCESS = "process"
    FLAKY_TEST = "flaky_test"
    WRONG_PLAN = "wrong_plan"
    OTHER = "other"
    UNKNOWN = "unknown"


class Stick(StrEnum):
    """What an answered ask became (dash-spec §5.3)."""

    ADR = "adr"
    REF = "ref"
    FACTORY = "factory"
    FIX = "fix"
    DEMOTE = "demote"
    ONCE = "once"
