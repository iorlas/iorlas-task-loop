"""`ask_json(bead, **over)`: a current-version ask record as the dict on disk (the quoted mock ask, re-pointed at `bead`)."""
import dataclasses
from typing import Any

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from asks.samples import MOCKS
from taskloop.contracts import codec


def ask_json(bead: str, n: int = 1, **over: Any) -> dict[str, Any]:
    rec = dataclasses.replace(MOCKS["lifesim-22b3"], bead=bead, id=f"{bead}-{n}")
    return {**codec.to_json(rec), **over}
