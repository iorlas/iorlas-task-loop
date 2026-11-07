"""Memory stores and recorders shared by the work stage fakes."""
from collections.abc import Callable, Sequence
from pathlib import Path

from tlgate.testing import FakeCheckout as GateCheckout
from tlgate.testing import FakeSteps as GateSteps
from tlkernel import fence
from tlkernel.adrs import AdrStore, decode_use
from tlkernel.checkpoint import Checkpoint, StageProgress
from tlkernel.checks import Check, CheckRun
from tlkernel.config import EngineConfig, HostResources
from tlkernel.ids import BeadId, CheckId, TreeSha
from tlkernel.ledger import Adr
from tlkernel.paths import ConfigDir
from tlkernel.plancheck import StageData
from tlkernel.stagefacts import RunFacts
from tlkernel.wire import Open
from tltestkit.memdoc import MemDoc, MemDocSet, MemLog, MemTickets


class FakeLog:
    """Narrate includes warn; FakeGateLog only supplies note and typed emission."""
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.warnings: list[str] = []

    def note(self, text: str) -> int:
        self.notes.append(text)
        return len(self.notes) - 1

    def warn(self, text: str) -> int:
        self.warnings.append(text)
        return len(self.warnings) - 1


class FakeSteps:
    """StepBook needs move/end and int begin offsets, so compose gate's None-returning steps."""
    def __init__(self) -> None:
        gate = GateSteps()
        self.calls, self.outcome = gate.calls, gate.outcome
        self.id = ""

    def begin(self, step: str, text: str, **meta: object) -> int:
        self.calls.append(("begin", (step, text), meta))
        self.id = f"step-{len(self.calls)}"
        return len(self.calls) - 1

    def move(self, to: str, cause: str, detail: str = "") -> None:
        self.calls.append(("move", (to, cause, detail), {}))

    def end(self, outcome: str = "") -> None:
        self.calls.append(("end", (outcome,), {}))


class MemCheckpoints:
    """Work checkpoint save/amend and retention recording wrap testkit MemDoc."""
    def __init__(self, bead: str, run: str, clock: Callable[[], float]) -> None:
        self.bead, self.run, self.clock = bead, run, clock
        self.doc = MemDoc(Checkpoint)
        self.kept: list[str] = []

    def read(self) -> Checkpoint | None:
        return self.doc.get()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "",
             progress: StageProgress | None = None) -> None:
        self.doc.write(Checkpoint(bead=self.bead, run=self.run, t=self.clock(), step=step, stage=stage, rounds=rounds,
                                  n=n, feedback=feedback, progress=progress))

    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool:
        return self.doc.modify(fn)

    def keep_pending(self, origin: str = "close") -> None:
        self.kept.append(f"pending:{origin}")

    def keep_look(self) -> None:
        self.kept.append("look")


class FakeWorkStores:
    """Work needs tickets and ADRs, without gate stores' filesystem leases."""
    def __init__(self) -> None:
        self.host = MemDoc(HostResources)
        self.tickets = MemTickets()
        self._runs: dict[tuple[str, int | None], MemDoc[CheckRun]] = {}
        self._adrs: dict[str, AdrStore] = {}

    def check_run(self, run: str, rnd: int | None) -> MemDoc[CheckRun]:
        return self._runs.setdefault((run, rnd), MemDoc(CheckRun))

    def adrs(self, repo: str) -> AdrStore:
        return self._adrs.setdefault(repo, AdrStore(MemDocSet(Adr), MemLog(decode_use)))


class FakeCheckout(GateCheckout):
    """Work checkout adds base, diff and slot status to the gate tree probe."""
    def __init__(self) -> None:
        super().__init__(TreeSha(""))
        self.base, self.diff = "base", ""
        self.unexplained: list[str] = []
        self.ignored: list[str] = []

    def base_sha(self) -> str:
        return self.base

    def task_diff(self) -> str:
        return self.diff

    def slot_status(self) -> tuple[list[str], list[str], str]:
        return list(self.unexplained), list(self.ignored), self.diff


class FakeChecks:
    """Work check ports consume queued runs; testkit checks builds results, not runners."""
    def __init__(self) -> None:
        self.round = 0
        self.answers: list[CheckRun] = []
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def answer(self, method: str, args: tuple[object, ...], meta: dict[str, object]) -> CheckRun:
        self.calls.append((method, args, meta))
        assert self.answers, f"{method}: no check answer queued"
        result = self.answers.pop(0)
        self.round = result.round
        return result

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = True, show_clean: bool = False,
                  clean: bool = False, all_files: bool = False) -> CheckRun:
        return self.answer("run_items", (list(items),), {"everything": everything, "learn": learn, "show_clean": show_clean,
                                                           "clean": clean, "all_files": all_files})

    def requested(self, ids: Sequence[CheckId], name: str, **meta: object) -> CheckRun:
        return self.answer("requested", (list(ids), name), meta)

    def stoppable(self, st: StageData, name: str, acceptance_first: bool = False, groups: Sequence[str] | None = None,
                  conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        return self.answer("stoppable", (st, name), dict(meta, acceptance_first=acceptance_first, groups=groups,
                                                        conflict_fix=conflict_fix))


class FakeLeftovers:
    """LeftoverSink deduplicates titles and keys; testkit has no matching sink."""
    def __init__(self, items: list[Open]) -> None:
        self.items = items
        self.keys: set[str] = set()

    def add_titled(self, lo: Open) -> bool:
        if any(row.get("title") == lo.get("title") for row in self.items):
            return False
        self.items.append(lo)
        return True

    def add_keyed(self, bead: str, lo: Open) -> bool:
        if bead in self.keys:
            return False
        self.keys.add(bead)
        self.items.append(lo)
        return True

    def extend(self, items: Sequence[Open]) -> None:
        self.items.extend(items)


def fake_facts(workdir: Path, cfg: EngineConfig | None = None, *, bead: str = "t-1", wt: Path | None = None,
               run_id: str = "FAKERUN0000") -> RunFacts:
    """Offline RunFacts and evidence folders, without run/repo helpers' database writes."""
    run = workdir / "runs" / run_id
    evidence = (wt or workdir / "wt") / "evidence"
    for path in (run / "task", run / "evidence", evidence):
        path.mkdir(parents=True, exist_ok=True)
    return RunFacts(bead=BeadId(bead), wt=str(wt or workdir / "wt"), cfg=cfg or EngineConfig(),
                    home=ConfigDir(workdir / "home"), run_id=run_id, run_dir=run, task_dir=run / "task",
                    brief_file=run / "task" / "brief.md", evidence_dir=evidence, repo="repo-id",
                    dry=False, fresh=False, claim=fence.offline(BeadId(bead)))
