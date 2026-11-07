"""The bd of this session and required or tolerant calls; command exit policy lives in cli."""
import shutil
from collections.abc import Callable

from taskloop.adapters.bd import BdStore
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.bdsafe import attempt, listed, peek
from taskloop.contracts.beadsport import BdFailure

__all__ = ["attempt", "bd_store", "listed", "peek"]


def bd_store(actor: str, cwd: object = None) -> BdStore:
    """The bd of the session `actor` names (adapters/bd.py, the one place that starts `bd`), asking the tracker of `cwd` (default: here)."""
    if not shutil.which("bd"):
        raise BdCommandFailure("tl: bd is not on PATH")
    return BdStore(actor, str(cwd) if cwd else None)


def must[**P, T](call: Callable[P, T], *args: P.args, **kw: P.kwargs) -> T:
    """A required bd operation; the CLI decides how to report its failure."""
    try:
        return call(*args, **kw)
    except BdFailure as e:
        raise BdCommandFailure("tl: " + e.error.text) from e
