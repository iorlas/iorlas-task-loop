"""`ask_json(bead, **over)`: a current-version ask record as the dict on disk (the quoted mock ask, re-pointed at `bead`)."""
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from typing import Any

from asks.samples import MOCKS

from tlkernel import wire
from tlkernel.askrows import AskRows
from tlkernel.askstore import AskStore
from tlkernel.paths import ConfigDir


def ask_json(bead: str, n: int = 1, **over: Any) -> dict[str, Any]:
    rec = MOCKS["lifesim-22b3"].replace(bead=bead, id=f"{bead}-{n}")
    return {**wire.dump(rec), **over}


def unreadable_ask(cfg: ConfigDir, bead: str, body: str) -> None:
    """Seed a row, then damage its stored wire body to exercise strict DB reads."""
    AskStore.at(cfg).put(MOCKS["lifesim-22b3"].replace(bead=bead, id=f"{bead}-1"))
    rows = AskRows(cfg)
    with rows.transaction():
        rows.connection().execute("UPDATE ask SET body=? WHERE bead=?", (body, bead))
