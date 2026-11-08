"""What a run records about itself: why it started, its run record in the engine log, its line in traces.jsonl."""
import contextlib
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel import lifecyclematchers as lifecycle
from tlkernel import log as rec
from tlkernel import plancheck, wire
from tlkernel import runoutcome as oc
from tlkernel import workswitch as switch
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
from tlkernel.repourl import repo_url
from tlkernel.run import LoopLogLine, Reexec, RunFinish, RunManifest, RunState
from tlkernel.slots import git_probe
from tlkernel.trace import RunTrace
from tlpipeline import ended, summaries
from tlpipeline import trace as runtrace
from tlpipeline.adapter_ports import Version
from tlpipeline.closing_record import RecordHost, RecordRun
from tlpipeline.finish import answer
from tlpipeline.finish import outcome as finished_outcome


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
    def account_notes(self) -> Sequence[str]: ...


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

class JournalActivity(Protocol):
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def budget(self) -> JournalBudget: ...
    @property
    def who(self) -> Identity: ...
    run_logged: bool
    @property
    def budget_warned(self) -> set[float]: ...

class JournalOutcome(Protocol):
    kind: Kind
    why: str
    disp: oc.Disposition | None
    fp: str
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...

class JournalTrace(Protocol):
    @property
    def stores(self) -> JournalTraces: ...
    @property
    def session(self) -> str: ...
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

class JournalProjection(Protocol):
    @property
    def dry(self) -> bool: ...
    @property
    def checkpoints(self) -> JournalCheckpoints: ...
    @property
    def env(self) -> Env: ...

class Journal:
    def __init__(self, origin: JournalOrigin, activity: JournalActivity, outcome: JournalOutcome,
                 trace: JournalTrace, projection: JournalProjection, records: RecordHost, facts: ended.HostFacts,
                 slot: Callable[[], str], repo_of: Callable[[Git, str | Path], str], version: Version) -> None:
        self.origin_role, self.activity, self.outcome = origin, activity, outcome
        self.trace, self.projection, self.records, self.facts = trace, projection, records, facts
        self.slot, self.repo_of = slot, repo_of
        self.version = version

    def origin(self) -> dict[str, str]:
        """Why this run started and the run before it: the checkpoint's run when there was one, else the bead's previous
        engine log. answer: an owner's answer to an ask; resume: the checkpoint was used; retry: an earlier run, no
        checkpoint used; fresh: --fresh; first: no earlier run."""
        prev = self.origin_role.ck_run or self.origin_role.prev_ck
        if not prev:
            mine = RunLocator(self.records.home).get(self.records.run_id)
            older = [b.run for b in RunLocator(self.records.home).of_bead(
                self.records.bead, self.repo_of(self.origin_role.git, self.origin_role.wt))
                     if b.run != self.records.run_id and (mine is None or b.started <= mine.started) and b.log.exists()]
            prev = older[-1] if older else ""
        why = ("reexec" if self.origin_role.reexec else "fresh" if self.origin_role.fresh
               else "answer" if self.origin_role.answered else "resume" if self.origin_role.resumed
               else "retry" if prev else "first")
        return {"prev_run": prev, "started_because": why,
                "ask": self.origin_role.answered.id if self.origin_role.answered else ""}

    def log_run(self) -> None:
        """The run record: why it started, once that is known (after the checkpoint is read), or at the close."""
        if self.activity.run_logged:
            return
        self.activity.run_logged = True
        if self.origin_role.reexec:  # the run record is in the log already (the exec kept the log): a note says what happened
            fallback = " (fallback after a crash)" if self.origin_role.reexec.fallback else ""
            self.records.log.note(f"task-loop {self.version() or '?'} took over run "
                                  f"{self.records.run_id} from {self.origin_role.reexec.frm}{fallback}")
            return
        bundle = RunLocator(self.records.home).get(self.records.run_id)
        why = self.origin()
        self.records.log.emit(
            rec.RunStart(
                worktree=self.origin_role.wt,
                slot=self.slot() or None,
                parent_id=why["prev_run"],
                started_because=why["started_because"],
                ask=why["ask"],
                branch=git_probe(lambda: self.origin_role.git.branch(self.origin_role.wt), ""),
                review=switch.mode(self.activity.cfg.review, self.activity.budget.labels),
                mode=bundle.manifest.mode if bundle else "",
                owner=self.activity.who.actor,
                session=self.activity.who.session,
            )
        )

    def heartbeat(self) -> None:
        """The run's tick in its manifest: running, alive as of now. Never raises: a manifest that cannot be written must not kill the
        beat thread."""
        with contextlib.suppress(OSError):
            RunLocator(self.records.home).beat(self.records.run_id, time.time())

    def settle(self, state: RunState, reason: str) -> None:
        """The run's one terminal state, on every exit path (the close-out calls it last, whatever happened before)."""
        try:
            bundle = RunLocator(self.records.home).get(self.records.run_id)
            if bundle is not None:
                candidate = previous_finish(bundle.manifest.replace(state=state, ended=time.time(), reason=reason, finish=None))
                finish_run(self.records.home, self.records.run_id, candidate, (lambda _m, _r: None) if self.projection.dry else None)
        except (OSError, ValueError) as err:
            self.records.warn(f"could not settle run {self.records.run_id}: {err}\n" + traceback.format_exc())

    def finish(self, done: oc.RunOutcome, stats: str = "",
               record: Callable[[RunFinish, str], None] | None = None) -> oc.RunOutcome:
        """Choose the run's answer before any close effect; all terminal evidence is projected by that call."""
        kept = ended.stored(self.records.run_id, done, self.outcome.disp, self.outcome.fp, self.outcome.leftovers)
        result = finish_run(self.records.home, self.records.run_id, answer(done, time.time(), kept),
                            lambda m, r: self.project(m, r, stats, record))
        winner = self.use(result.record)
        if not result.won:
            self.records.warn(f"run {self.records.run_id} already finished as {result.record.state}: keeping the first answer")
        return winner

    def use(self, record: RunFinish) -> oc.RunOutcome:
        """Restore the winner before projecting it, including when a different process repairs its history."""
        winner = finished_outcome(record)
        self.outcome.kind, self.outcome.why = winner.kind, winner.detail
        if record.end:
            _, self.outcome.disp, self.outcome.fp = ended.loaded(wire.load(EndRec, record.end))
        else:
            self.outcome.disp = oc.apply(winner, self.records.bead, [], record.ended)
            self.outcome.fp = winner.fingerprint
        return winner

    def project(self, manifest: RunManifest, record: RunFinish, stats: str,
                emit: Callable[[RunFinish, str], None] | None = None) -> None:
        self.use(record)
        if not self.projection.dry and record.end:
            self.projection.checkpoints.keep_end(ended.intent_of(wire.load(EndRec, record.end), self.facts, stats))
        (emit or RecordRun(self.records).run)(record, stats)
        indexes(self.records.home, manifest, record, LoopLogLine(
            slot=self.projection.env.get(EnvVar.TASK_LOOP_SLOT) or self.slot() or "", outcome=record.result,
            minutes=round((record.ended - self.trace.t0) / 60, 1), rounds=self.trace.stats.get("rounds", 0),
            tests_added=self.trace.stats.get("tests_added", 0), asked=self.facts.asked, engine_log=str(self.trace.log_path),
            run_log=self.projection.env.get(EnvVar.TASK_LOOP_RUN_LOG)))

    def file_trace(self, record: RunFinish) -> None:
        """One line per engine run in traces.jsonl: age-pruned by tl prune, retaining every LANDED record."""
        outcome, why, sha, kind = record.outcome, record.why, record.sha, record.kind
        try:
            if any(str(i.rec.run) == self.records.run_id for i in self.trace.stores.traces.read_from(0).items):
                return
            self.trace.stores.traces.append(
                runtrace.run_trace(
                    self.records.run_id,
                    dict(
                        self.origin(),
                        bead=self.records.bead,
                        repo_url=git_probe(lambda: repo_url(self.origin_role.git, self.origin_role.wt), self.origin_role.wt),
                        worktree=self.origin_role.wt,
                        branch=git_probe(lambda: self.origin_role.git.branch(self.origin_role.wt), ""),
                        coordinator_session=self.trace.session,
                        version=self.version(),
                        started=self.trace.t0,
                        ended=record.ended,
                        outcome=outcome,
                        why=(why or "")[:500],
                        sha=sha or "",
                        kind=kind,
                        kfp=self.outcome.fp,
                        why_code=record.why_code,
                        fingerprint=lifecycle.run_fingerprint(outcome, why),
                        cost=self.trace.cost,
                        stats=self.trace.stats,
                        delegate_path=self.trace.route or "",
                        log=str(self.trace.log_path),
                        stderr=str(self.trace.err_path),
                        sessions=self.trace.sessions,
                        verified=self.trace.review.verified,
                        write_rounds=self.trace.write.write_rounds,
                        strays=self.trace.write.strays,
                        reflection=self.records.reflection,
                        account_notes=self.trace.write.account_notes,
                        salvaged=self.trace.land_state.salvaged,
                    ),
                )
            )
        except (OSError, ValueError) as err:
            self.records.warn(f"could not write the trace: {err}")
            raise

    def after_call(self, c: JournalCall, res: DelegateResult) -> None:
        """A node's answer was taken: its detail lines, then what was odd about it."""
        assert res.data is not None
        plancheck.parse(res.data)  # from here on a check is a Ref or an Adhoc
        self.records.detail(summaries.details(c.node, res.data))
        self.anomalies(c.node, res, c.tries)

    def anomalies(self, node: str, r: DelegateResult, attempt: int) -> None:
        if attempt > 1:
            self.records.warn(f"{node} needed a retry to produce valid output")
        if node != "write" and r.secs > float(self.activity.cfg.node_timeout_min) * 60 * 0.6:  # a write follows its worker's activity
            self.records.warn(f"{node} took {int(r.secs // 60)} min, close to the {self.activity.cfg.node_timeout_min} min limit")
        spent = self.activity.budget.used()
        for mark in (0.5, 0.8):
            if spent > mark and mark not in self.activity.budget_warned:
                self.activity.budget_warned.add(mark)
                self.records.warn(f"{spent * 100:.0f}% of the task's budget is used")
        if node == "review" and r.data is not None and any(f["severity"] == "high" for f in r.data["findings"]):
            self.records.warn("the reviewer found a high-severity problem")
