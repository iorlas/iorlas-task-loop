"""What a run records about itself: why it started, its run record in the engine log, its line in traces.jsonl."""
import contextlib
import time
import traceback
from collections.abc import Callable
from typing import Any

from taskloop.adapters import ident
from taskloop.adapters.repourl import repo_url
from taskloop.app.pipeline import ended, summaries
from taskloop.app.pipeline import trace as runtrace
from taskloop.app.pipeline.closing_record import RecordRun
from taskloop.app.pipeline.finish import answer
from taskloop.app.pipeline.finish import outcome as finished_outcome
from taskloop.app.run.layout import repo_of
from taskloop.app.slots import engine_lock
from taskloop.contracts import log as rec
from taskloop.contracts import plancheck, wire
from taskloop.contracts.checkpoint import EndRec
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.finish import finish_run, previous_finish
from taskloop.contracts.finish_projection import indexes
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import LoopLogLine, RunFinish, RunManifest, RunState
from taskloop.contracts.slots import git_probe
from taskloop.domain import outcome as oc
from taskloop.domain.lifecycle import matchers as lifecycle
from taskloop.domain.review import switch


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
        bundle = RunLocator(e.home).get(e.run_id)
        why = self.origin()
        e.log.emit(
            rec.RunStart(
                worktree=str(e.wt),
                slot=(lock.rec.slot if lock else "") or None,
                parent_id=why["prev_run"],
                started_because=why["started_because"],
                ask=why["ask"],
                branch=git_probe(lambda: e.git.branch(e.wt), ""),
                review=switch.mode(e.cfg.review, e.budget.labels),
                mode=bundle.manifest.mode if bundle else "",
                owner=e.who.actor,
                session=e.who.session,
            )
        )

    def heartbeat(self) -> None:
        """The run's tick in its manifest: running, alive as of now. Never raises: a manifest that cannot be written must not kill the
        beat thread."""
        with contextlib.suppress(OSError):
            RunLocator(self.e.home).beat(self.e.run_id, time.time())

    def settle(self, state: RunState, reason: str) -> None:
        """The run's one terminal state, on every exit path (the close-out calls it last, whatever happened before)."""
        try:
            e = self.e
            bundle = RunLocator(e.home).get(e.run_id)
            if bundle is not None:
                candidate = previous_finish(bundle.manifest.replace(state=state, ended=time.time(), reason=reason, finish=None))
                finish_run(e.home, e.run_id, candidate, (lambda _m, _r: None) if e.dry else None)
        except (OSError, ValueError) as err:
            self.e.warn(f"could not settle run {self.e.run_id}: {err}\n" + traceback.format_exc())

    def finish(self, done: oc.RunOutcome, stats: str = "",
               record: Callable[[RunFinish, str], None] | None = None) -> oc.RunOutcome:
        """Choose the run's answer before any close effect; all terminal evidence is projected by that call."""
        e = self.e
        kept = ended.stored(e.run_id, done, e.disp, e.fp, e.leftovers)
        result = finish_run(e.home, e.run_id, answer(done, time.time(), kept),
                            lambda m, r: self.project(m, r, stats, record))
        winner = self.use(result.record)
        if not result.won:
            e.warn(f"run {e.run_id} already finished as {result.record.state}: keeping the first answer")
        return winner

    def use(self, record: RunFinish) -> oc.RunOutcome:
        """Restore the winner before projecting it, including when a different process repairs its history."""
        winner = finished_outcome(record)
        self.e.kind, self.e.why = winner.kind, winner.detail
        if record.end:
            _, self.e.disp, self.e.fp = ended.loaded(wire.load(EndRec, record.end))
        else:
            self.e.disp = oc.apply(winner, self.e.bead, [], record.ended)
            self.e.fp = winner.fingerprint
        return winner

    def project(self, manifest: RunManifest, record: RunFinish, stats: str,
                emit: Callable[[RunFinish, str], None] | None = None) -> None:
        e = self.e
        self.use(record)
        if not e.dry and record.end:
            e.checkpoints.keep_end(wire.load(EndRec, record.end))
        (emit or RecordRun(e).run)(record, stats)
        lock = engine_lock.LOCK
        indexes(e.home, manifest, record, LoopLogLine(
            slot=e.env.get(EnvVar.TASK_LOOP_SLOT) or (lock.rec.slot if lock else "") or "", outcome=record.result,
            minutes=round((record.ended - e.t0) / 60, 1), rounds=e.stats.get("rounds", 0),
            tests_added=e.stats.get("tests_added", 0), asked=e.asked, engine_log=str(e.log_path),
            run_log=e.env.get(EnvVar.TASK_LOOP_RUN_LOG)))

    def file_trace(self, record: RunFinish) -> None:
        """One line per engine run in traces.jsonl: age-pruned by tl prune, retaining every LANDED record."""
        e = self.e
        outcome, why, sha, kind = record.outcome, record.why, record.sha, record.kind
        try:
            if any(str(i.rec.run) == e.run_id for i in e.stores.traces.read_from(0).items):
                return
            e.stores.traces.append(
                runtrace.run_trace(
                    e.run_id,
                    dict(
                        self.origin(),
                        bead=e.bead,
                        repo_url=git_probe(lambda: repo_url(e.git, str(e.wt)), str(e.wt)),
                        worktree=str(e.wt),
                        branch=git_probe(lambda: e.git.branch(e.wt), ""),
                        coordinator_session=e.session,
                        version=ident.plugin_version(),
                        started=e.t0,
                        ended=record.ended,
                        outcome=outcome,
                        why=(why or "")[:500],
                        sha=sha or "",
                        kind=kind,
                        kfp=e.fp,
                        why_code=record.why_code,
                        fingerprint=lifecycle.run_fingerprint(outcome, why),
                        cost=e.cost,
                        stats=e.stats,
                        delegate_path=e.route or "",
                        log=str(e.log_path),
                        stderr=str(e.err_path),
                        sessions=e.sessions,
                        verified=e.review.verified,
                        write_rounds=e.write.write_rounds,
                        strays=e.write.strays,
                        reflection=e.reflection,
                        lane_notes=e.write.lane_notes,
                        salvaged=e.land_state.salvaged,
                    ),
                )
            )
        except (OSError, ValueError) as err:
            e.warn(f"could not write the trace: {err}")
            raise

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
