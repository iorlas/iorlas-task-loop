"""`ask_json(bead, **over)`: a current-version ask record as the dict on disk (the quoted mock ask, re-pointed at `bead`)."""
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from typing import Any

from asks.samples import MOCKS

from taskloop.contracts import wire


def ask_json(bead: str, n: int = 1, **over: Any) -> dict[str, Any]:
    rec = MOCKS["lifesim-22b3"].model_copy(update={"bead": bead, "id": f"{bead}-{n}"})
    return {**wire.dump(rec), **over}
