"""Existing disk record shapes projected from a manifest's winning finish."""
from collections.abc import Callable

from taskloop.contracts import events, log
from taskloop.contracts.guard import guard
from taskloop.contracts.ids import RunId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import LoopLogLine, RunFinish, RunManifest
from taskloop.contracts.stores import EventLog, LoopLog, RunLog, TraceStore
from taskloop.contracts.trace import RunTrace


def indexes(cfg: ConfigDir, m: RunManifest, done: RunFinish, row: LoopLogLine | None = None) -> None:
    """A stage event records the run's end; bead close/block events still describe bead mutations."""
    with guard(cfg.lock_record("log", "events")):
        events_log = EventLog(cfg)
        if not any(i.rec.run_id == m.run and i.rec.step == "close" for i in events_log.read_from().items):
            events_log.append(events.Stage(t=done.ended, run_id=m.run, bead=m.bead, host=m.host,
                                           session=m.session, actor=m.owner, repo=m.repo, sha=done.sha,
                                           step="close", text=f"close: {done.outcome}"))
    if m.loop:
        row = row or LoopLogLine(slot="", outcome=done.result)
        loop = LoopLog(cfg, m.loop)
        if not any(i.rec.run_id == m.run for i in loop.read_from().items):
            loop.append(row.replace(t=done.ended, run_id=m.run, bead=m.bead, host=m.host,
                                    outcome=done.result, sha=done.sha, why=done.why[:300]))


def history(cfg: ConfigDir, m: RunManifest, done: RunFinish, *,
            emit: Callable[[log.Close], object] | None = None,
            append_trace: Callable[[RunTrace], object] | None = None, repo_url: str = "", with_trace: bool = True,
            index: bool = True) -> None:
    """A dead run or a standalone verb has no engine host; its manifest supplies the same projections."""
    close = log.Close(t=done.ended, run_id=m.run, bead=m.bead, host=m.host, sha=done.sha,
                      outcome=done.outcome, why_code=done.why_code, why=done.why[:500])
    engine = RunLog(cfg, m.run)
    if not any(isinstance(i.rec, log.Close) for i in engine.read_from().items):
        (emit or engine.append)(close)
    run_id = RunId.of(m.run)
    traces = TraceStore(cfg)
    if with_trace and run_id is not None and not any(i.rec.run == run_id for i in traces.read_from().items):
        (append_trace or TraceStore(cfg).append)(RunTrace(run=run_id, bead=m.bead, repo_url=repo_url or m.repo, repo_path=m.repo,
                                       worktree=m.worktree or m.repo, branch=m.branch, coordinator_session=m.session,
                                       started=m.started, ended=done.ended, outcome=done.outcome, why=done.why[:500],
                                       sha=done.sha, kind=done.kind, why_code=done.why_code))
    if index:
        indexes(cfg, m, done)
