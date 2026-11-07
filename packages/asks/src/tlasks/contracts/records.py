"""Values and machine services supplied to asks by its consumers."""
from collections.abc import Callable
from dataclasses import dataclass

from tlkernel.askport import AskReader
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.enums import WhyCode
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir


@dataclass(frozen=True)
class Arguments:
    """An owner operation, independent of the command-line parser."""

    op: str
    bead: BeadId | None = None
    text: tuple[str, ...] = ()
    json: bool = False
    option: int | None = None
    verdict: str | None = None
    rerun: bool = False
    confirm: bool = False
    split: bool = False
    amend: bool = False
    expect: str | None = None
    waive: str | None = None
    defer: str | None = None
    drop: str | None = None
    approval: str | None = None
    until: str | None = None
    release: bool = False


@dataclass(frozen=True)
class Asking:
    """Where and when an ask is raised."""

    bead: BeadId
    run: str
    brief_hash: str
    repo: str
    title: str
    now: float
    why: str = ""
    why_code: WhyCode | None = None
    artifacts: tuple[str, ...] = ()  # store ids of the pictures that show the owner what the stop is about


@dataclass(frozen=True)
class AsksHost:
    bd: Callable[[str, str], Beads]
    peek: Callable[[Beads, BeadId], Bead | None]
    hostname: Callable[[], str]
    asks_store: Callable[[ConfigDir], AskReader]
    now: Callable[[], float]
    plugin_version: Callable[[], str]
