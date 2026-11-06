"""The checks port: running the workflow checks and probing a tree, with the typed spec and result."""
from typing import Protocol, final

import msgspec

from taskloop.contracts.argv import text_of
from taskloop.contracts.wire import Rec


@final
class CheckSpec(Rec):
    argv: list[str]
    cwd: str
    timeout_s: float = 3600.0
    env: dict[str, str] = msgspec.field(default_factory=dict)

    @property
    def cmd(self) -> str:
        return text_of(self.argv)


@final
class CheckResult(Rec):
    exit: int
    out: str = ""
    secs: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit == 0 and not self.timed_out


class TreeProbe(Protocol):
    """What the plan-check lint may ask of the tree and the machine a check will run on."""

    def has_command(self, word: str) -> bool:
        """True when the word resolves to an executable on the tree's PATH (shutil.which)."""
        ...
    def recipes(self) -> set[str] | None:
        """The recipe and alias names of the tree's justfile, None when there is no just or no justfile."""
        ...
    def exists(self, path: str) -> bool:
        """The path (relative to the tree, or absolute) exists."""
        ...
    def is_dir(self, path: str) -> bool: ...


class Checks(Protocol):
    def run(self, spec: CheckSpec) -> CheckResult:
        """Run one command (an argv, no shell). Exit 124 and `timed_out` when the time ran out."""
        ...
