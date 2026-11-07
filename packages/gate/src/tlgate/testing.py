"""Small recording fakes for the capabilities a gate host supplies."""
import shutil
import weakref
from pathlib import Path

from any_lease import Leases
from tlkernel.checks import BaseRedRecord, CheckRun, Durations, PassRecord
from tlkernel.config import HostResources
from tlkernel.log import EngineLog, Note
from tlkernel.storeapi import Passes
from tlkernel.waitenums import WaitWhat
from tltestkit.memdoc import MemDoc, MemDocSet
from tltestkit.tmpdir import mkdtemp


class FakeGateLog:
    def __init__(self) -> None:
        self.records: list[EngineLog] = []
        self.ids = 0

    def emit(self, rec: EngineLog) -> int:
        offset = len(self.records)
        self.records.append(rec)
        return offset

    def note(self, text: str) -> int:
        return self.emit(Note(text=text))

    def next_id(self, prefix: str) -> str:
        self.ids += 1
        return f"{prefix}{self.ids}"


class FakeSteps:
    def __init__(self, id: str = "") -> None:
        self.id = id
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def begin(self, step: str, text: str, **meta: object) -> None:
        self.calls.append(("begin", (step, text), meta))

    def outcome(self, outcome: str, detail: str = "") -> None:
        self.calls.append(("outcome", (outcome, detail), {}))


class RecordedWaits:
    """WaitsView: the waits a check reported, kept in a list."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, float]] = []

    def note_slot_waits(self, text: str, wall: float) -> None:
        self.seen.append((text, wall))

    def start(self, what: WaitWhat, holder: str = "", until: float | None = None, lane: str = "", check: str = "") -> str:
        return f"w{len(self.seen)}"

    def add(self, secs: float, what: WaitWhat, wid: str | None = None, lane: str = "", check: str = "") -> None:
        self.seen.append((what.value, secs))


class FakeGateStores:
    def __init__(self) -> None:
        self._passes: dict[tuple[str, str], MemDocSet[PassRecord]] = {}
        self._reds: dict[str, MemDocSet[BaseRedRecord]] = {}
        self._runs: dict[tuple[str, int | None], MemDoc[CheckRun]] = {}
        self.durations = MemDocSet(Durations)
        self.host = MemDoc(HostResources)
        root = mkdtemp(prefix="tl-leases-")
        self.leases = Leases(Path(root))
        weakref.finalize(self.leases, shutil.rmtree, root, True)

    def results(self, repo: str, check: str) -> Passes:
        return self._passes.setdefault((repo, check), MemDocSet(PassRecord))

    def base_red(self, repo: str) -> MemDocSet[BaseRedRecord]:
        return self._reds.setdefault(repo, MemDocSet(BaseRedRecord))

    def check_run(self, run: str, rnd: int | None) -> MemDoc[CheckRun]:
        return self._runs.setdefault((run, rnd), MemDoc(CheckRun))
