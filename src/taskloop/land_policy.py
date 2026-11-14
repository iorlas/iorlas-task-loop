"""Typed landing policy and its presentation vocabulary, shared by status consumers."""

from dataclasses import dataclass
from enum import StrEnum

from taskloop.profile import LandMode


class LandState(StrEnum):
    WAITING = "waiting"
    MANUAL = "manual"
    UNKNOWN = "unknown"
    LANDING = "landing"
    FINISHING = "finishing"


@dataclass(frozen=True)
class LandPolicy:
    mode: LandMode | None = None
    commit: str | None = None


def decision(policy: LandPolicy, *, running: bool = False, delivered: bool = False) -> LandState:
    if delivered:
        return LandState.FINISHING
    if running:
        return LandState.LANDING
    if policy.mode is LandMode.AUTO:
        return LandState.WAITING
    return LandState.MANUAL if policy.mode is LandMode.MANUAL else LandState.UNKNOWN


def words(state: LandState) -> str:
    return {
        LandState.WAITING: "Waiting for the factory to land it",
        LandState.MANUAL: "Waiting for a person to approve delivery",
        LandState.UNKNOWN: "Landing policy is unavailable",
        LandState.LANDING: "Land is in progress",
        LandState.FINISHING: "The factory is finishing delivery",
    }[state]
