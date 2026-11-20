"""Small edges of a `tl rounds start` process: what it says on stderr and how a failed open reads between rounds."""

import os
import sys
from collections.abc import Callable
from pathlib import Path

from taskloop.operation_failure import Failed


def transient(refused: Failed, database: Path) -> Failed:
    if refused.reason == "database" and database.exists():
        return Failed("unavailable", "store", "factory.db exists but could not be opened now")
    return refused


def unlogged(artifacts: Path) -> Callable[[], None]:
    def warn() -> None:
        print(f"Log: not written ({artifacts / 'rounds.log'})", file=sys.stderr)

    return warn


def say(text: str) -> None:
    os.write(2, (text + "\n").encode())  # unbuffered: the SIGINT handler may say it while the process writes stderr
