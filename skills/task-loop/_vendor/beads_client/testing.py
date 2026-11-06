"""A scripted bd for tests: queue replies, read back the argv that was run. No pytest import."""

from __future__ import annotations

from beads_client.runner import BdRun


class Script:
    """A Runner that answers from a queue (an empty queue answers exit 0, no output) and records every argv."""

    def __init__(self) -> None:
        self.replies: list[BdRun] = []
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], _cwd: str | None) -> BdRun:
        self.calls.append(argv)
        return self.replies.pop(0) if self.replies else BdRun(0, "", "")

    def say(self, out: str = "", err: str = "", code: int = 0) -> Script:
        self.replies.append(BdRun(code, out, err))
        return self
