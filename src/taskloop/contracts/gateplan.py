"""The neutral version-one document a repo's gate-plan command prints."""
from typing import Literal, final

from taskloop.contracts.wire import Rec


@final
class GatePlanStep(Rec, forbid_unknown_fields=False):
    lane: str
    run: bool
    argv: list[str]
    pre: list[list[str]]
    recipe: str | None
    name: str | None = None
    reason: str | None = None
    id: str | None = None
    why: str | None = None


@final
class GatePlan(Rec, forbid_unknown_fields=False):
    version: Literal[1]
    base: str | None
    empty: bool
    full: bool
    full_reasons: list[str]
    steps: list[GatePlanStep]
