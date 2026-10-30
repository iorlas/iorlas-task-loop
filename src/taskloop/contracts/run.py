"""Run records: what a run-task process reports to its loop, and the hand-over between two engine versions."""
import json
from typing import Any, ClassVar, final

import msgspec

from taskloop.contracts import wire
from taskloop.contracts.enums import Result, WhyCode
from taskloop.contracts.ids import BeadId
from taskloop.contracts.wire import Rec, Refused


@final
class RunReport(Rec):
    """The last line run-task prints and loop/<key>/<bead>-<stamp>.outcome.json. `kind` is the outcome.Kind value ("" for a stop
    before the engine ran); a file of another `v` or with an unknown outcome is a parse error, never a default."""

    V: ClassVar[int] = 2
    outcome: Result
    bead: BeadId
    run: str = ""
    why_code: WhyCode | None = None
    why: str = ""
    log: str = ""
    minutes: float = 0.0
    rounds: int = 0
    tests_added: int = 0
    asked: bool = False
    retry_after: float | None = None
    cost: float = 0.0
    kind: str = ""
    fingerprint: str = ""
    storm: str = ""
    role: str = ""
    lane: str = ""


@final
class LoopLogLine(Rec):
    """A line of loop/<key>.jsonl: one bead's run as the loop saw it. A line without this `v` (the earlier bare dicts) is not read."""

    V: ClassVar[int] = 3
    ts: str
    bead: BeadId
    slot: str
    outcome: Result
    minutes: float = 0.0
    rounds: int = 0
    tests_added: int = 0
    asked: bool = False
    trace: str = ""
    engine_log: str = ""
    run_log: str = ""
    why: str = ""


@final
class Reexec(Rec):
    """The TL_REEXEC hand-over (an environment variable, JSON of this record): what an engine that moves into a newer install, or the
    loop that puts a crashed move back on the old one, tells the run-task it starts. `owned`: the slot the old process took itself;
    `fallback`: the loop restarted the run on the install it came from."""

    V: ClassVar[int] = 1
    run: str
    bead: str
    frm: str = msgspec.field(name="from")
    owned: str = ""
    fallback: bool = False

    def text(self) -> str:
        return json.dumps(wire.dump(self))

    @classmethod
    def parse(cls, raw: str) -> Reexec | None:
        """The hand-over in `raw` (the TL_REEXEC text); None for "". A text that is not a Reexec of this version is Refused, naming the
        variable: a run-task never starts as a fresh run when its parent meant it to go on."""
        if not raw:
            return None
        try:
            return wire.load(cls, raw)
        except ValueError as err:
            raise Refused(f"TL_REEXEC is not a Reexec v{cls.V} ({err}): {raw[:200]!r}") from None


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
class Round(Rec):
    """One writer/review round, as the next writer is told of it (app/write/handoff)."""

    stage: str
    round: int
    kind: str
    writer: str = ""  # what the writer said, cut
    open: list[str] = msgspec.field(default_factory=list)  # what the review sent back, cut


@final
class HandoffMirror(Rec):
    """runs/<run>/handoff.json: a copy of the writer's handoff (rounds so far, lows already noted) for whoever reads the run dir."""

    V: ClassVar[int] = 1
    rounds: list[Round] = msgspec.field(default_factory=list)
    seen_lows: list[str] = msgspec.field(default_factory=list)
    deferred: list[dict[str, str]] = msgspec.field(default_factory=list)
    filed: list[Any] = msgspec.field(default_factory=list)
