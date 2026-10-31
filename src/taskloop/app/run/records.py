"""What a run records about itself: why it started, its run record in the engine log, its line in traces.jsonl."""
import contextlib
import time
from typing import Any

from taskloop.adapters import ident
from taskloop.adapters.repourl import repo_url
from taskloop.app.run import summaries
from taskloop.app.run import trace as runtrace
from taskloop.app.run.layout import repo_of
from taskloop.app.slots import engine_lock
from taskloop.contracts import log as rec
from taskloop.contracts import plancheck
from taskloop.contracts.enums import Outcome, Result
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunState
from taskloop.domain import outcome as oc
from taskloop.domain.report import matchers as lifecycle
from taskloop.domain.review import switch


def terminal_state(outcome: oc.RunOutcome) -> RunState:
    """The state a run ends in: its policy row's result (landed or done -> done, a fault -> failed, an ask or park -> parked, a pause
    or a signal -> stopped)."""
    result = outcome.rule.loop
    if result is Result.LANDED:
        return RunState.DONE
    if result is Result.PARKED:
        return RunState.PARKED
    if result is Result.PAUSED:
        return RunState.STOPPED
    return RunState.FAILED


class Records:
    def __init__(self, host: Any) -> None:
        self.e = host

    def origin(self) -> dict[str, str]:
        """Why this run started and the run before it: the checkpoint's run when there was one, else the bead's previous
        engine log. answer: an owner's answer to an ask; resume: the checkpoint was used; retry: an earlier run, no
        checkpoint used; fresh: --fresh; first: no earlier run."""
        e = self.e
        prev = e.ck_run or e.prev_ck
        if not prev:
            mine = RunLocator(e.home).get(e.run_id)
            older = [b.run for b in RunLocator(e.home).of_bead(e.bead, repo_of(e.git, e.wt))
                     if b.run != e.run_id and (mine is None or b.started <= mine.started) and b.log.exists()]
            prev = older[-1] if older else ""
        why = ("reexec" if e.reexec else "fresh" if e.fresh else "answer" if e.answered else "resume" if e.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": lifecycle.normalize_started_because(why, prev),
                "ask": e.answered.id if e.answered else ""}

    def log_run(self) -> None:
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        e = self.e
        if e.run_logged:
            return
        e.run_logged = True
        if e.reexec:  # the run record is in the log already (the exec kept the log): a note says what happened
            fallback = " (fallback after a crash)" if e.reexec.fallback else ""
            e.log.note(f"task-loop {ident.plugin_version() or '?'} took over run {e.run_id} from {e.reexec.frm}{fallback}")
            return
        lock = engine_lock.LOCK
        why = self.origin()
        e.log.emit(
            rec.RunStart(
                worktree=str(e.wt),
                slot=(lock.rec.slot if lock else "") or None,
                parent_id=why["prev_run"],
                started_because=why["started_because"],
                ask=why["ask"],
                branch=e.git.branch(e.wt),
                review=switch.mode(e.cfg.review, e.budget.labels),
            )
        )

    def heartbeat(self) -> None:
        """The run's tick in its manifest: running, alive as of now. Never raises: a manifest that cannot be written must not kill the
        beat thread."""
        with contextlib.suppress(OSError):
            RunLocator(self.e.home).beat(self.e.run_id, time.time())

    def settle(self, state: RunState, reason: str) -> None:
        """The run's one terminal state, on every exit path (the close-out calls it last, whatever happened before)."""
        with contextlib.suppress(OSError):
            RunLocator(self.e.home).end(self.e.run_id, time.time(), state, reason)

    def file_trace(self, outcome: Outcome, why: str, sha: str) -> None:
        """One line per engine run in traces.jsonl, never pruned: bead, repo, branch, every session, the outcome."""
        e = self.e
        kind = e.kind.value
        try:
            e.stores.traces.append(
                runtrace.run_trace(
                    e.run_id,
                    dict(
                        self.origin(),
                        bead=e.bead,
                        repo_url=repo_url(e.git, str(e.wt)),
                        worktree=str(e.wt),
                        branch=e.git.branch(e.wt),
                        coordinator_session=e.session,
                        version=ident.plugin_version(),
                        started=e.t0,
                        ended=time.time(),
                        outcome=outcome,
                        why=(why or "")[:500],
                        sha=sha or "",
                        kind=kind,
                        kfp=e.fp,
                        why_code=runtrace.why_code(kind, outcome),
                        fingerprint=lifecycle.run_fingerprint(outcome, why),
                        cost=e.cost,
                        stats=e.stats,
                        delegate_path=e.route or "",
                        log=str(e.log_path),
                        stderr=str(e.err_path),
                        sessions=e.sessions,
                        verified=e.verified,
                        write_rounds=e.write_rounds,
                        strays=e.strays,
                        reflection=e.reflection,
                        lane_notes=e.lane_notes,
                        salvaged=e.salvaged,
                    ),
                )
            )
        except (OSError, ValueError) as err:
            e.warn(f"could not write the trace: {err}")

    def after_call(self, c: Any, res: Any) -> None:
        """A node's answer was taken: its detail lines, then what was odd about it."""
        e = self.e
        plancheck.parse(res.data)  # from here on a check is a Ref or an Adhoc
        e.detail(summaries.details(c.node, res.data))
        self.anomalies(c.node, res, c.tries)

    def anomalies(self, node: str, r: Any, attempt: int) -> None:
        e = self.e
        if attempt > 1:
            e.warn(f"{node} needed a retry to produce valid output")
        if node != "write" and r.secs > float(e.cfg.node_timeout_min) * 60 * 0.6:  # a write follows its worker's activity
            e.warn(f"{node} took {int(r.secs // 60)} min, close to the {e.cfg.node_timeout_min} min limit")
        spent = e.budget.used()
        for mark in (0.5, 0.8):
            if spent > mark and mark not in e.budget_warned:
                e.budget_warned.add(mark)
                e.warn(f"{spent * 100:.0f}% of the task's budget is used")
        if node == "review" and any(f["severity"] == "high" for f in r.data["findings"]):
            e.warn("the reviewer found a high-severity problem")
