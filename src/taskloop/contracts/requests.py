"""OwnerRequest: what the owner asked of one live run (`tl park|stop|note`, POST /api/park|stop|note). One file per run
(ConfigDir.run_request); writers merge into it under its lock, and the run takes it whole: stop at its Beat or next step boundary,
park and the notes at its next step boundary. A request for a run that ended is refused, and one left at the close is dropped."""
from typing import ClassVar

import msgspec

from taskloop.contracts.wire import Rec


class OwnerNote(Rec):
    text: str
    t: float
    by: str


class OwnerRequest(Rec):
    V: ClassVar[int] = 1
    park: bool = False  # end the run at the next step boundary; the branch and the checkpoint stay, the bead is parked
    stop: bool = False  # end the run now, through its stop flag (the halt path a SIGTERM takes)
    notes: list[OwnerNote] = msgspec.field(default_factory=list)  # for the next stage's worker, oldest first
    by: str = ""  # who asked last
    t: float = 0.0  # when
