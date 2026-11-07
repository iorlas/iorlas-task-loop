"""First-writer-wins completion in factory.db, with separately serialized file projections."""
from collections.abc import Callable
from dataclasses import dataclass

from tlkernel import attemptrows
from tlkernel.enums import Outcome, Result
from tlkernel.finish_projection import history
from tlkernel.guard import guard
from tlkernel.paths import ConfigDir
from tlkernel.run import RunFinish, RunManifest, RunState
from tlkernel.runrows import RunRows


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


class BeatMoved(ValueError):
    """The run beat after the caller decided it was lost: it is alive, so nothing is written."""


def finish_run(cfg: ConfigDir, run: str, candidate: RunFinish,
               project: Callable[[RunManifest, RunFinish], None] | None = None, *, seen_beat: float | None = None) -> FinishResult:
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
        if seen_beat is not None and old.state.live and old.heartbeat != seen_beat:
            raise BeatMoved(run)  # checked in the transaction that would write the answer: a beat in between keeps the run alive
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
