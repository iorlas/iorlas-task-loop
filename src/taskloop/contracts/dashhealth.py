"""Project identity and the health of its last bd listing, as published by the dashboard."""

from typing import final

from taskloop.contracts.wire import Rec


@final
class Score(Rec):
    """The M2 scorecard of `tl report` for a window, as the dashboard's strip shows it: the same numbers (app/report/card.py scorecard)."""

    since: float
    until: float
    beads: int
    landed: int
    landed_no_ask: int
    asks: int
    lost: int
    crashes: int
    m2_pass: bool
    main_red: bool = False  # a revert landed on main since the window began (app/report/mainstate.py)


@final
class Project(Rec):
    id: str
    name: str
    profile_error: str = ""
    bd_ok_at: float | None = None
    bd_error: str = ""
    score: Score | None = None
