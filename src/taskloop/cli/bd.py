"""Translate failures of required bd operations into the command's historical exit diagnostic."""
import sys
from collections.abc import Callable

from taskloop.contracts.bd_errors import BdCommandFailure


def required[**P, T](call: Callable[P, T], *args: P.args, **kw: P.kwargs) -> T:
    """Run a command, exiting with its diagnostic when a required bd operation fails."""
    try:
        return call(*args, **kw)
    except BdCommandFailure as error:
        sys.exit(str(error))
