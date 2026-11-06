"""First-writer-wins completion in factory.db, with separately serialized file projections."""
from collections.abc import Callable
from dataclasses import dataclass

from taskloop.contracts import attemptrows
from taskloop.contracts.enums import Outcome, Result
from taskloop.contracts.finish_projection import history
from taskloop.contracts.guard import guard
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunFinish, RunManifest, RunState
from taskloop.contracts.runrows import RunRows


@dataclass(frozen=True)
class FinishResult:
    record: RunFinish
    won: bool


def previous_finish(m: RunManifest) -> RunFinish:
    """Older terminal manifests remain authoritative even before they carried a complete finish record."""
    if m.finish is not None:
        return m.finish
    outcome, result, kind = {
        RunState.DONE: (Outcome.DONE, Result.LANDED, "done"),
        RunState.PARKED: (Outcome.BLOCKED, Result.PARKED, "owner_park"),
        RunState.STOPPED: (Outcome.FAILED, Result.PAUSED, "pause_killed"),
    }.get(m.state, (Outcome.FAILED, Result.FAILED, "fault_engine"))
    return RunFinish(state=m.state, ended=m.ended if m.ended is not None else m.heartbeat,
                     outcome=outcome, result=result, kind=kind, why=m.reason, sha=m.sha)


def finish_run(cfg: ConfigDir, run: str, candidate: RunFinish,
               project: Callable[[RunManifest, RunFinish], None] | None = None) -> FinishResult:
    """Atomically choose a terminal answer; serialize and recover its projections under a separate lock.

    A missing or unreadable manifest is an error, never permission to invent a second authority.
    Projection failures propagate. Later callers repair missing projections from the winner, never their own candidate.
    """
    if candidate.state.live:
        raise ValueError(f"{candidate.state} is not a terminal state")
    doc = RunRows(cfg)
    with doc.transaction() as con:
        old = doc.read(con, run)
        if old is None or old.run != run:
            raise ValueError(f"no manifest for run {run}")
        won = old.state.live
        record = candidate if won else previous_finish(old)
        if won:
            doc.write(con, old.replace(state=record.state, ended=record.ended, heartbeat=record.ended,
                                       reason=record.why, sha=record.sha, finish=record, finish_projected=False))
        attemptrows.close(con, run, record, candidate.ended)
    with guard(cfg.lock_record("finish-history", run)):
        winner = doc.get(run)
        assert winner is not None
        if not winner.finish_projected:
            if project is None:
                history(cfg, winner, record)
            else:
                project(winner, record)
            doc.change(run, lambda current: current.replace(finish_projected=True))
    return FinishResult(record, won)
