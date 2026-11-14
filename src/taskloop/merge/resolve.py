"""Bounded resolution executions, with registration and evidence separate from the ordinary step."""

import json
import threading
from collections.abc import Callable
from contextlib import suppress

from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from any_agent.procs import Worker

from taskloop.agents.launch import AgentLaunch, LaunchFailure
from taskloop.attempt_types import AttemptKey, FileRef, WorkerGone
from taskloop.command_sink import CommandSink, WatchedHooks
from taskloop.drain.models import Identity
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.merge.models import Answer, Artifact, Execution, InProgress, Reason, Unavailable, Waiting, Work
from taskloop.merge.store import MergeStore

type Run = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]


def key(work: Work, number: int) -> AttemptKey:
    return AttemptKey(f"{work.attempt_id}/merge/{number}", work.dispatch_token, work.generation)


class Resolution:
    def __init__(self, store: MergeStore, agent: AgentLaunch, files: EvidenceFiles, run: Run,
                 gone: WorkerGone, clock: Callable[[], float], fence: Callable[[], None]) -> None:
        self.store, self.agent, self.files, self.run = store, agent, files, run
        self.gone, self.clock, self.fence = gone, clock, fence
        self.lock = threading.Lock()

    def __call__(self, work: Work) -> Work | Waiting:
        last = work.executions[-1] if work.executions else None
        if last is not None and not last.ended and last.worker is not None:
            worker = last.worker
            if not self.gone(Worker(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot)):
                return InProgress(reason=Reason.UNKNOWN,
                                  explanation="The merge resolution process may still be running; its reservation is retained.")
            last = last.model_copy(update={"ended": True,
                                           "explanation": last.explanation or "The resolution process stopped before capture."})
            if last.capturing:
                last = self._captured(last)
            work = self._execution(work, last)
        if last is not None and last.ended and not last.reviewed:
            return work
        if last is not None and last.capturing and last.worker is None:
            return Unavailable(reason=Reason.UNKNOWN,
                               explanation="The resolution capture has no confirmed process identity; work stays reserved.")
        unregistered = last is not None and last.worker is None and not last.ended
        if len(work.executions) >= 3 and not unregistered:
            return work
        number = len(work.executions) + 1
        if last is not None and unregistered:
            number = last.number  # registration never committed, so no target could have executed
        launch_key = key(work, number)
        schema, out_file = self.files.prepare(launch_key, Answer.model_json_schema())
        prompt = self._prompt(work)
        input_ref = self.files.put_input(launch_key, prompt)
        launch = self.agent.build(work.setting, work.slot, True, self.files.launch_root(launch_key), schema, out_file, prompt)
        if isinstance(launch, LaunchFailure):
            return Unavailable(reason=Reason.UNKNOWN, explanation=launch.explanation)
        try:
            self.fence()
            if last is None or number != last.number:
                execution = Execution(number=number, input=Artifact(path=input_ref.path, digest=input_ref.digest))
                work = self.store.put(work, work.model_copy(update={"executions": (*work.executions, execution)}))
            hooks = WatchedHooks(started=lambda worker: self._register(work.attempt_id, number, worker),
                                 ref=lambda ref: self._session(work.attempt_id, number, ref), unattended=False,
                                 live=CommandSink(self.files, launch_key, self.clock))
            raw = self.run(launch.harness, launch.spec, max(0, work.deadline - self.clock()), hooks)
            return self._capture(work, number, raw)
        finally:
            launch.harness.cleanup()

    def _capture(self, work: Work, number: int, raw: RunOutcome) -> Work | Waiting:
        session = raw.summary.res.get("ref")
        if isinstance(session, str) and session:
            self._session(work.attempt_id, number, session)
        latest = self.store.get(work.attempt_id)
        if latest is None:
            return Unavailable(reason=Reason.UNKNOWN, explanation="The merge execution record is unavailable.")
        result = latest.executions[-1]
        identity = None if raw.worker is None else Identity(pid=raw.worker.pid, pgid=raw.worker.pgid,
                                                           start=raw.worker.start, boot=raw.worker.boot)
        matching = identity is not None and identity == result.worker
        answer = None
        if (matching and raw.rc == 0 and not raw.timed_out and raw.summary.stands and not result.session_conflict
                and not raw.stop and not raw.secret and not raw.watch.why):
            with suppress(ValueError):
                answer = Answer.model_validate_json(raw.summary.text)
        evidence = self.files.capture_refs(key(work, number), raw)
        refs = tuple(Artifact(path=ref.path, digest=ref.digest) for ref in
                     (evidence.stdout, evidence.stderr, evidence.answer, evidence.diagnostics))
        explanation = ("The resolution returned a validated answer." if answer is not None else
                       "The resolution timed out." if raw.timed_out else
                       f"The resolution exited with code {raw.rc}; no valid answer was accepted.")
        if not matching:
            explanation = "The resolution result names a different process; its answer cannot be accepted."
        result = result.model_copy(update={"answer": answer, "evidence": refs, "capturing": True, "rc": raw.rc,
                                          "timed_out": raw.timed_out, "explanation": explanation})
        latest = self._execution(latest, result)  # capture intent precedes every artifact write
        self.files.capture(key(work, number), raw)
        ended = raw.worker is not None and matching and self.gone(raw.worker)
        result = self._captured(result).model_copy(update={"ended": ended})
        latest = self._execution(latest, result)
        return latest if ended else InProgress(reason=Reason.UNKNOWN,
                              explanation="Resolution evidence is captured; process stop is not yet confirmed.")

    def _captured(self, result: Execution) -> Execution:
        try:
            for ref in result.evidence:
                self.files.read(FileRef(ref.path, ref.digest))
        except EvidenceError:
            # The completed process is gone and never duplicated. Retain its edits, mark its uncaptured execution,
            # and allow another execution within the same durable limit, with those edits as context.
            return result.model_copy(update={"capturing": False, "answer": None, "reviewed": True,
                                             "explanation": "The stopped execution's capture was interrupted; its edits are retained."})
        return result.model_copy(update={"capturing": False})

    def _execution(self, work: Work, execution: Execution) -> Work:
        return self.store.put(work, work.model_copy(update={"executions": (*work.executions[:-1], execution)}))

    def _register(self, attempt_id: str, number: int, worker: Worker) -> None:
        with self.lock:
            self.fence()
            work = self.store.get(attempt_id)
            if work is None or work.executions[-1].number != number or self.clock() >= work.deadline:
                raise ValueError("merge registration changed or expired")
            identity = Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot)
            if work.executions[-1].worker not in (None, identity):
                raise ValueError("merge worker changed")
            self._execution(work, work.executions[-1].model_copy(update={"worker": identity}))

    def _session(self, attempt_id: str, number: int, ref: str) -> None:
        with self.lock:
            work = self.store.get(attempt_id)
            if work is None or not work.executions or work.executions[-1].number != number:
                return
            execution = work.executions[-1]
            conflict = execution.session_conflict or execution.session not in (None, ref)
            self._execution(work, execution.model_copy(update={"session": execution.session or ref, "session_conflict": conflict}))

    def _prompt(self, work: Work) -> str:
        requirements = self.files.read(FileRef(work.input_path, work.input_digest))
        return ("The retained step input below is task context; this execution only resolves the stopped merge.\n"
                + requirements + f"\n\nResolve the stopped merge for task {work.task_id}. Retain the task's work and current main.\n"
                f"Source commit: {work.source}\nTarget main commit: {work.target}\nConflict paths: {json.dumps(work.conflicts)}\n"
                "The committed plan is available at docs/design/<task-id>/plan.md in the source commit. "
                "Edit plain files only. Do not run Git writes, stage, commit, abort or move refs. "
                "Retain automatic merge changes. Report every edited or deleted path exactly. "
                "Leave Git metadata, .beads, executable files and symlinks untouched. "
                "Return needs_owner for semantic ambiguity; do not weaken checks or tests to resolve a conflict.\n")
