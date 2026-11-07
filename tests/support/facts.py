"""A RunFacts and RunPorts without an Engine (docs/design/facts.md): what a stage reads of its run, built from the fakes the tests already
use (FakeClock, fake_stores, the real RunLog/Steps/CheckLog over the in-memory log). tests/run/test_facts_contract.py runs the same probes
against this and a real Engine, so the two cannot drift."""
from collections.abc import Callable, Sequence
from pathlib import Path

import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.memcheckpoints import MemCheckpointDoc
from support.memstores import fake_stores
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.pipeline.steps import Steps
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog
from taskloop.stores.runports import RunPorts
from tlkernel import fence
from tlkernel.checkpoint import Checkpoint, StageProgress
from tlkernel.checks import Check, CheckResult, CheckRun
from tlkernel.config import EngineConfig
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir
from tlkernel.plancheck import PlanCheck
from tlkernel.ports import Clock
from tlkernel.stagefacts import RunFacts
from tltestkit.cfgs import cfg_with
from tltestkit.fake_clock import FakeClock


class MemCheckpoints:
    """CheckpointsPort over one in-memory record. `keep_*` only record that a keep was asked (they read engine state in the real one)."""

    def __init__(self, bead: str, run: str, clock: Callable[[], float]) -> None:
        self.bead, self.run, self.clock = bead, run, clock
        self.doc = MemCheckpointDoc(bead)
        self.kept: list[str] = []

    def read(self) -> Checkpoint | None:
        return self.doc.get()

    def save(self, *, step: str = "", stage: int = 0, rounds: int = 0, n: int = 0, feedback: str = "",
             progress: StageProgress | None = None) -> None:
        self.doc.write(Checkpoint(bead=self.bead, run=self.run, t=self.clock(), step=step, stage=stage, rounds=rounds, n=n,
                                  feedback=feedback, progress=progress))

    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool:
        return self.doc.modify(fn)

    def keep_look(self) -> None:
        self.kept.append("look")

    def keep_pending(self, origin: str = "close") -> None:
        self.kept.append(f"pending:{origin}")

    def keep_filed(self, lost: list[dict[str, str]] | None = None) -> None:
        self.kept.append("filed")

    def mark_applied(self, key: str) -> None:
        self.amend(lambda ck: ck.replace(applied=[*ck.applied, key]))

    def applied(self) -> frozenset[str]:
        ck = self.read()
        return frozenset(ck.applied) if ck else frozenset()


class FakeChecker:
    """CheckerPort answering the results it was given, round after round."""

    def __init__(self, results: Sequence[CheckResult] = ()) -> None:
        self.results, self.n = list(results), 0

    def run(self, stage_checks: Sequence[PlanCheck], name: str, markers: str = "", acceptance_first: bool = False,
            groups: Sequence[str] | None = None, conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
        return self.run_items([])

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = True, show_clean: bool = False,
                  clean: bool = False, all_files: bool = False) -> CheckRun:
        self.n += 1
        return CheckRun(round=self.n, results=list(self.results), misses=len(self.results))

    def gate_green(self, clean: bool = False) -> bool:
        return not any(r.status == "failed" for r in self.results)


class FakeRepoKey:
    def __init__(self, key: str) -> None:
        self.value, self.calls = key, 0

    def key(self) -> str:
        self.calls += 1
        return self.value


def fake_facts(workdir: Path, bead: str = "t-1", cfg: EngineConfig | None = None, dry: bool = False, fresh: bool = False, *,
               wt: Path | None = None, home: ConfigDir | None = None, run_id: str = "FAKERUN0000", stores: Stores | None = None,
               clock: Clock | None = None) -> tuple[RunFacts, RunPorts]:
    """Facts and ports of a run that never ran: its folders are made under `workdir`, its log and stores are in memory, its bd is a
    FakeBeads. `dry` and `fresh` are the two flags a test sets; `wt`, `home`, `run_id`, `stores` and `clock` are the pieces a test
    that shares them with other fakes brings."""
    run_dir = workdir / "runs" / run_id
    for sub in ("task", "evidence"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    clock, stores = clock or FakeClock(), stores or fake_stores()
    log = RunLog(stores.run_log(run_id), clock=clock.now, run_id=run_id, bead=bead, host="host")
    ports = RunPorts(
        clock=clock, env=snapshot(), git=port_git(), spawner=real_spawner(), steps=Steps(log, clock.now), log=log,
        checklog=CheckLog(log), store=FakeBeads(), stores=stores, checkpoints=MemCheckpoints(bead, run_id, clock.now),
        checker=FakeChecker(), repo=FakeRepoKey("repo-key"),
    )
    facts = RunFacts(
        bead=BeadId(bead), wt=str(wt or workdir / "wt"), cfg=cfg or cfg_with(EngineConfig()), home=home or who().config, run_id=run_id,
        run_dir=run_dir, task_dir=run_dir / "task", brief_file=run_dir / "task" / "brief.md", evidence_dir=run_dir / "evidence",
        repo="repo-id", dry=dry, fresh=fresh, claim=fence.offline(BeadId(bead)),
    )
    return facts, ports
