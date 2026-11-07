"""What a run records about itself: why it started, its run record in the engine log, its line in traces.jsonl."""
import contextlib
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel import log as rec
from tlkernel import plancheck, wire
from tlkernel.ask import Ask
from tlkernel.checkpoint import CloseIntent, EndRec
from tlkernel.config import EngineConfig
from tlkernel.delegate import DelegateResult
from tlkernel.docstore import Ledger
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.finish import finish_run, previous_finish
from tlkernel.finish_projection import indexes
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.run import LoopLogLine, Reexec, RunFinish, RunManifest, RunState
from tlkernel.slots import git_probe
from tlkernel.trace import RunTrace

from taskloop.adapters import ident
from taskloop.adapters.repourl import repo_url
from taskloop.app.pipeline import ended, summaries
from taskloop.app.pipeline import trace as runtrace
from taskloop.app.pipeline.closing_record import RecordHost, RecordRun
from taskloop.app.pipeline.finish import answer
from taskloop.app.pipeline.finish import outcome as finished_outcome
from taskloop.domain import outcome as oc
from taskloop.domain.lifecycle import matchers as lifecycle
from taskloop.domain.work import switch


class JournalCall(Protocol):
    @property
    def node(self) -> str: ...
    @property
    def tries(self) -> int: ...


class JournalBudget(Protocol):
    @property
    def labels(self) -> list[str]: ...
    def used(self) -> float: ...


class JournalCheckpoints(Protocol):
    def keep_end(self, intent: CloseIntent) -> None: ...


class JournalReview(Protocol):
    @property
    def verified(self) -> Sequence[Mapping[str, object]]: ...


class JournalWrite(Protocol):
    @property
    def write_rounds(self) -> Sequence[Mapping[str, object]]: ...
    @property
    def strays(self) -> Sequence[str]: ...
    @property
    def lane_notes(self) -> Sequence[str]: ...


class JournalLand(Protocol):
    @property
    def salvaged(self) -> bool: ...


class JournalTraces(Protocol):
    @property
    def traces(self) -> Ledger[RunTrace]: ...


class JournalOrigin(Protocol):
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def ck_run(self) -> str: ...
    @property
    def prev_ck(self) -> str: ...
    @property
    def reexec(self) -> Reexec | None: ...
    @property
    def fresh(self) -> bool: ...
    @property
    def answered(self) -> Ask | None: ...
    @property
    def resumed(self) -> bool: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def budget(self) -> JournalBudget: ...
    @property
    def who(self) -> Identity: ...
    run_logged: bool


class JournalFinish(Protocol):
    kind: Kind
    why: str
    disp: oc.Disposition | None
    fp: str
    @property
    def checkpoints(self) -> JournalCheckpoints: ...
    @property
    def dry(self) -> bool: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...


class JournalTrace(Protocol):
    @property
    def session(self) -> str: ...
    @property
    def stores(self) -> JournalTraces: ...
    @property
    def env(self) -> Env: ...
    @property
    def t0(self) -> float: ...
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def log_path(self) -> Path: ...
    @property
    def cost(self) -> float: ...
    @property
    def route(self) -> str: ...
    @property
    def err_path(self) -> Path: ...
    @property
    def sessions(self) -> Sequence[Mapping[str, object]]: ...
    @property
    def review(self) -> JournalReview: ...
    @property
    def write(self) -> JournalWrite: ...
    @property
    def land_state(self) -> JournalLand: ...


class JournalWarnings(Protocol):
    @property
    def budget_warned(self) -> set[float]: ...


class Journal:
    def __init__(self, origin_state: JournalOrigin, terminal: JournalFinish, tracing: JournalTrace,
                 warnings: JournalWarnings, recording: RecordHost, facts: ended.HostFacts,
                 slot: Callable[[], str], repo_of: Callable[[Git, str | Path], str]) -> None:
        self.origin_state, self.terminal, self.tracing = origin_state, terminal, tracing
        self.warnings, self.recording, self.facts = warnings, recording, facts
        self.slot, self.repo_of = slot, repo_of

    def origin(self) -> dict[str, str]:
        """Why this run started and the run before it: the checkpoint's run when there was one, else the bead's previous
        engine log. answer: an owner's answer to an ask; resume: the checkpoint was used; retry: an earlier run, no
        checkpoint used; fresh: --fresh; first: no earlier run."""
        prev = self.origin_state.ck_run or self.origin_state.prev_ck
        if not prev:
            mine = RunLocator(self.recording.home).get(self.recording.run_id)
            older = [b.run for b in RunLocator(self.recording.home).of_bead(
                self.recording.bead, self.repo_of(self.origin_state.git, self.origin_state.wt))
                     if b.run != self.recording.run_id and (mine is None or b.started <= mine.started) and b.log.exists()]
            prev = older[-1] if older else ""
        why = ("reexec" if self.origin_state.reexec else "fresh" if self.origin_state.fresh else "answer" if self.origin_state.answered
               else "resume" if self.origin_state.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": why,
                "ask": self.origin_state.answered.id if self.origin_state.answered else ""}

    def log_run(self) -> None:
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        if self.origin_state.run_logged:
            return
        self.origin_state.run_logged = True
        if self.origin_state.reexec:  # the run record is in the log already (the exec kept the log): a note says what happened
            fallback = " (fallback after a crash)" if self.origin_state.reexec.fallback else ""
            self.recording.log.note(f"task-loop {ident.plugin_version() or '?'} took over run {self.recording.run_id} "
                                    f"from {self.origin_state.reexec.frm}{fallback}")
            return
        bundle = RunLocator(self.recording.home).get(self.recording.run_id)
        why = self.origin()
        self.recording.log.emit(
            rec.RunStart(
                worktree=self.origin_state.wt,
                slot=self.slot() or None,
                parent_id=why["prev_run"],
                started_because=why["started_because"],
                ask=why["ask"],
                branch=git_probe(lambda: self.origin_state.git.branch(self.origin_state.wt), ""),
                review=switch.mode(self.origin_state.cfg.review, self.origin_state.budget.labels),
                mode=bundle.manifest.mode if bundle else "",
                owner=self.origin_state.who.actor,
                session=self.origin_state.who.session,
            )
        )

    def heartbeat(self) -> None:
        """The run's tick in its manifest: running, alive as of now. Never raises: a manifest that cannot be written must not kill the
        beat thread."""
        with contextlib.suppress(OSError):
            RunLocator(self.recording.home).beat(self.recording.run_id, time.time())

    def settle(self, state: RunState, reason: str) -> None:
        """The run's one terminal state, on every exit path (the close-out calls it last, whatever happened before)."""
        try:
            bundle = RunLocator(self.recording.home).get(self.recording.run_id)
            if bundle is not None:
                candidate = previous_finish(bundle.manifest.replace(state=state, ended=time.time(), reason=reason, finish=None))
                finish_run(self.recording.home, self.recording.run_id, candidate, (lambda _m, _r: None) if self.terminal.dry else None)
        except (OSError, ValueError) as err:
            self.recording.warn(f"could not settle run {self.recording.run_id}: {err}\n" + traceback.format_exc())

    def finish(self, done: oc.RunOutcome, stats: str = "",
               record: Callable[[RunFinish, str], None] | None = None) -> oc.RunOutcome:
        """Choose the run's answer before any close effect; all terminal evidence is projected by that call."""
        kept = ended.stored(self.recording.run_id, done, self.terminal.disp, self.terminal.fp, self.terminal.leftovers)
        result = finish_run(self.recording.home, self.recording.run_id, answer(done, time.time(), kept),
                            lambda m, r: self.project(m, r, stats, record))
        winner = self.use(result.record)
        if not result.won:
            self.recording.warn(f"run {self.recording.run_id} already finished as {result.record.state}: keeping the first answer")
        return winner

    def use(self, record: RunFinish) -> oc.RunOutcome:
        """Restore the winner before projecting it, including when a different process repairs its history."""
        winner = finished_outcome(record)
        self.terminal.kind, self.terminal.why = winner.kind, winner.detail
        if record.end:
            _, self.terminal.disp, self.terminal.fp = ended.loaded(wire.load(EndRec, record.end))
        else:
            self.terminal.disp = oc.apply(winner, self.recording.bead, [], record.ended)
            self.terminal.fp = winner.fingerprint
        return winner

    def project(self, manifest: RunManifest, record: RunFinish, stats: str,
                emit: Callable[[RunFinish, str], None] | None = None) -> None:
        self.use(record)
        if not self.terminal.dry and record.end:
            self.terminal.checkpoints.keep_end(ended.intent_of(wire.load(EndRec, record.end), self.facts, stats))
        (emit or RecordRun(self.recording).run)(record, stats)
        indexes(self.recording.home, manifest, record, LoopLogLine(
            slot=self.tracing.env.get(EnvVar.TASK_LOOP_SLOT) or self.slot() or "", outcome=record.result,
            minutes=round((record.ended - self.tracing.t0) / 60, 1), rounds=self.tracing.stats.get("rounds", 0),
            tests_added=self.tracing.stats.get("tests_added", 0), asked=self.facts.asked, engine_log=str(self.tracing.log_path),
            run_log=self.tracing.env.get(EnvVar.TASK_LOOP_RUN_LOG)))

    def file_trace(self, record: RunFinish) -> None:
        """One line per engine run in traces.jsonl: age-pruned by tl prune, retaining every LANDED record."""
        outcome, why, sha, kind = record.outcome, record.why, record.sha, record.kind
        try:
            if any(str(i.rec.run) == self.recording.run_id for i in self.tracing.stores.traces.read_from(0).items):
                return
            self.tracing.stores.traces.append(
                runtrace.run_trace(
                    self.recording.run_id,
                    dict(
                        self.origin(),
                        bead=self.recording.bead,
                        repo_url=git_probe(lambda: repo_url(self.origin_state.git, self.origin_state.wt), self.origin_state.wt),
                        worktree=self.origin_state.wt,
                        branch=git_probe(lambda: self.origin_state.git.branch(self.origin_state.wt), ""),
                        coordinator_session=self.tracing.session,
                        version=ident.plugin_version(),
                        started=self.tracing.t0,
                        ended=record.ended,
                        outcome=outcome,
                        why=(why or "")[:500],
                        sha=sha or "",
                        kind=kind,
                        kfp=self.terminal.fp,
                        why_code=record.why_code,
                        fingerprint=lifecycle.run_fingerprint(outcome, why),
                        cost=self.tracing.cost,
                        stats=self.tracing.stats,
                        delegate_path=self.tracing.route or "",
                        log=str(self.tracing.log_path),
                        stderr=str(self.tracing.err_path),
                        sessions=self.tracing.sessions,
                        verified=self.tracing.review.verified,
                        write_rounds=self.tracing.write.write_rounds,
                        strays=self.tracing.write.strays,
                        reflection=self.recording.reflection,
                        lane_notes=self.tracing.write.lane_notes,
                        salvaged=self.tracing.land_state.salvaged,
                    ),
                )
            )
        except (OSError, ValueError) as err:
            self.recording.warn(f"could not write the trace: {err}")
            raise

    def after_call(self, c: JournalCall, res: DelegateResult) -> None:
        """A node's answer was taken: its detail lines, then what was odd about it."""
        assert res.data is not None
        plancheck.parse(res.data)  # from here on a check is a Ref or an Adhoc
        self.recording.detail(summaries.details(c.node, res.data))
        self.anomalies(c.node, res, c.tries)

    def anomalies(self, node: str, r: DelegateResult, attempt: int) -> None:
        if attempt > 1:
            self.recording.warn(f"{node} needed a retry to produce valid output")
        if node != "write" and r.secs > float(self.origin_state.cfg.node_timeout_min) * 60 * 0.6:  # a write follows its worker's activity
            self.recording.warn(f"{node} took {int(r.secs // 60)} min, close to the {self.origin_state.cfg.node_timeout_min} min limit")
        spent = self.origin_state.budget.used()
        for mark in (0.5, 0.8):
            if spent > mark and mark not in self.warnings.budget_warned:
                self.warnings.budget_warned.add(mark)
                self.recording.warn(f"{spent * 100:.0f}% of the task's budget is used")
        if node == "review" and r.data is not None and any(f["severity"] == "high" for f in r.data["findings"]):
            self.recording.warn("the reviewer found a high-severity problem")
