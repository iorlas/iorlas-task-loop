"""Project identity and the health of its last bd listing, as published by the dashboard."""

from typing import final

from taskloop.contracts.wire import Rec


@final
class Project(Rec):
    id: str
    name: str
    profile_error: str = ""
    bd_ok_at: float | None = None
    bd_error: str = ""
