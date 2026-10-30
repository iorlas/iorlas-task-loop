"""Run records: what a run-task process reports to its loop, and the hand-over between two engine versions."""
from typing import Any, ClassVar, final

import msgspec

from taskloop.contracts.enums import Outcome, WhyCode
from taskloop.contracts.wire import Rec


@final
class RunOutcome(Rec):
    """The last line run-task prints and loop/<key>/<bead>-<stamp>.outcome.json."""

    V: ClassVar[int] = 2
    outcome: Outcome
    bead: str
    run: str
    why_code: WhyCode | None = None
    why: str = ""
    log: str = ""
    minutes: float = 0.0
    rounds: int = 0
    tests_added: int = 0
    asked: bool = False
    retry_after: float | None = None
    cost: float = 0.0


@final
class LoopLogLine(Rec):
    """A line of loop/<key>.jsonl: the outcome plus where it ran."""

    V: ClassVar[int] = 2
    outcome: RunOutcome
    t: float
    slot: str | None = None
    run_log: str = ""


@final
class Reexec(Rec):
    """runs/<run>/reexec.json: the one record an old process writes and a newer install reads (TL_REEXEC)."""

    V: ClassVar[int] = 1
    run: str
    bead: str
    from_version: str
    to_version: str
    step: str
    owned: list[str] = msgspec.field(default_factory=list)
    fallback: str = ""
    counters: dict[str, int] = msgspec.field(default_factory=dict)


@final
class RunCounters(Rec):
    """runs/<run>/pause.json and reexec.json: what a run had spent when it paused for the network or exec'd into a newer install, so
    its cost, time and trace go on across the move."""

    V: ClassVar[int] = 1
    elapsed: float
    waited: float
    cost: float
    stats: dict[str, int]
    sessions: list[dict[str, Any]]
    write_rounds: list[Any]
    node_n: int


@final
class ReexecNote(Rec):
    """reexec/<bead>.json: left just before an engine execs into a newer install; the loop reads it once, to say what happened."""

    V: ClassVar[int] = 1
    run: str
    bead: str
    frm: str = msgspec.field(name="from")
    to: str
    step: str
    from_dir: str
    t: float


@final
class NetPause(Rec):
    """pauses/<bead>.json: left by a run that paused for the network; the next run-task of the bead takes the same run up again."""

    V: ClassVar[int] = 1
    run: str
    bead: str
    t: float


@final
class DoneEntry(Rec):
    sha: str
    file: str


@final
class DoneMemo(Rec):
    """runs/<run>/done.json: the answers a run already took, by call key (a JSON list) -> the prompt's sha and the raw copy's file."""

    V: ClassVar[int] = 1
    done: dict[str, DoneEntry] = msgspec.field(default_factory=dict)


@final
class HandoffMirror(Rec):
    """runs/<run>/handoff.json: a copy of the writer's handoff (rounds so far, lows already noted) for whoever reads the run dir."""

    V: ClassVar[int] = 1
    rounds: list[dict[str, Any]] = msgspec.field(default_factory=list)
    seen_lows: list[str] = msgspec.field(default_factory=list)
    deferred: list[dict[str, str]] = msgspec.field(default_factory=list)
    filed: list[Any] = msgspec.field(default_factory=list)
