"""The durable flake score log for one repository."""
from typing import ClassVar

import msgspec

from tlkernel.wire import Rec


class FlakeRow(Rec):
    test: str
    t: float
    how: str
    run: str = ""
    bead: str = ""


class FlakeLog(Rec):
    V: ClassVar[int] = 1
    rows: list[FlakeRow] = msgspec.field(default_factory=list)
