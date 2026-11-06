"""The one place a bd process starts. A runner is ``(argv, cwd) -> BdRun``; tests inject a scripted one."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

EXIT_PRECONDITION = 13  # bd: every failure was a stale --if-assignee/--if-status guard
EXIT_TIMEOUT = 124
EXIT_MISSING = 127


@dataclass(frozen=True)
class BdRun:
    code: int
    out: str
    err: str


Runner = Callable[[list[str], str | None], BdRun]


def subprocess_runner(argv: list[str], cwd: str | None, timeout: float | None = None) -> BdRun:
    """Run bd; a missing binary is code 127 and a timeout code 124, never an exception."""
    try:
        r = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except OSError as e:
        return BdRun(EXIT_MISSING, "", f"bd: {e}")
    except subprocess.TimeoutExpired:
        return BdRun(EXIT_TIMEOUT, "", f"bd: no answer in {timeout}s")
    return BdRun(r.returncode, r.stdout, r.stderr)
