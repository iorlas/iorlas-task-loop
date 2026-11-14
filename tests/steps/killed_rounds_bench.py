"""Round completion over a reopened file database and retained external semantic fakes."""

import json
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from doubles import PinnedViews
from git_porcelain.testing import FakeWorktree
from plan_fixtures import PLAN_TEXT
from round_bench import Factory, Tracker
from sqlite_store import begin_immediate
from test_recovery import Processes

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_types import Admission, AttemptKey, Evidence, ExecutionFacts, SlotFiles, VerifyResult
from taskloop.drain.models import Identity, Seen
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.hold_store import HoldStore
from taskloop.ids import NativeIds
from taskloop.launch import Launched, LaunchResult
from taskloop.publish import BranchPublish, PublishResult
from taskloop.recovery.complete_attempt import CapturedCompletion
from taskloop.recovery.continuation_models import State
from taskloop.recovery.continue_attempt import Continuation
from taskloop.recovery.execution_models import Callback
from taskloop.recovery.launch import RecoveryLaunch
from taskloop.recovery.models import Claim, ClaimState, Outcome
from taskloop.recovery.native import NativeContinuation
from taskloop.recovery.recover import Recovery
from taskloop.recovery.store import RecoveryStore
from taskloop.round import RoundPorts
from taskloop.slot_lock import hold
from taskloop.slot_release import ReleaseResult, SlotRelease
from taskloop.verifier import Verifier

PLAN = "docs/design/tl-1/plan.md"
OWNER = Identity(pid=80, pgid=80, start="restarted-entry", boot="boot")
WORKER = Worker(pid=90, pgid=90, start="resumed-worker", boot="boot")


class Killed(BaseException):
    """An abrupt disappearance, outside ordinary application error handling."""


@dataclass
class Effects:
    stop: str = "session"
    calls: list[LaunchSpec] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    processes: Processes = field(default_factory=Processes)

    def after(self, boundary: str) -> None:
        if self.stop == boundary:
            self.stop = ""
            raise Killed(boundary)


def connect(path: Path, *, initialize: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    if initialize:
        with begin_immediate(con):
            for statement in SCHEMA.ddl.split(";"):
                if statement.strip():
                    con.execute(statement)
            con.execute(f"PRAGMA user_version={SCHEMA.version}")
    return con


class RestartFactory(Factory):
    def __init__(
        self, con: sqlite3.Connection, tmp: Path, slot: FakeWorktree, views: PinnedViews, files: SlotFiles,
        tracker: Tracker, effects: Effects, patch: pytest.MonkeyPatch, *, adopted: bool = False,
    ) -> None:
        super().__init__(con, tmp, slot, views, files, tracker, adopted=adopted)
        self.effects, self.patch = effects, patch
        self.agents["tl-1", "plan"] = self.execute_agent
        capture = self.store.capture

        def captured(
            admission: Admission, worker: Worker | None, facts: ExecutionFacts, evidence: Evidence,
            session_state: Literal["complete", "pending", "conflict", "fault"], callback: Callback | None = None,
        ) -> Literal["accepted", "already_same", "conflict"]:
            result = capture(admission, worker, facts, evidence, session_state, callback)
            effects.after("capture")
            return result

        patch.setattr(self.store, "capture", captured)
        if not adopted:
            self.install_hooks()

    def execute_agent(self, _harness: Harness, spec: LaunchSpec, _timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.effects.calls.append(spec)
        assert hooks is not None and hooks.started is not None and hooks.ref is not None
        resumed = "resume" in spec.argv
        worker = WORKER if resumed else Worker(pid=42, pgid=42, start="original", boot="boot")
        hooks.started(worker)
        hooks.ref("saved-session")
        self.slot.write_file(PLAN, PLAN_TEXT)
        self.effects.after("session")
        assert resumed and "saved-session" in spec.argv
        answer = {"disposition": "planned", "plan_path": PLAN, "paths": [PLAN], "message": "Plan", "explanation": "planned"}
        return RunOutcome(rc=0, worker=worker, summary=Summary(text=json.dumps(answer), res={"ref": "saved-session"}))

    def attempts(self) -> Attempts:
        return Attempts(self.store, EvidenceFiles(self.tmp), AgentLaunch(lambda _h: ("/bin/codex", {}), ids=NativeIds()),
                        self.execute_agent, lambda: self.now, self.checkouts, self.files)

    def recovery(self) -> Recovery:
        def claim(admission: Admission) -> Claim:
            self.effects.claims.append(admission.task.task_id)
            bead = self.tracker.beads[admission.task.task_id]
            state = ClaimState.OWNED if bead.assignee == "taskloop" and bead.status == "in_progress" else ClaimState.LOST
            return Claim(state=state, explanation="Observed the retained task claim.")

        return Recovery(RecoveryStore(lambda: self.con), self.effects.processes, claim, hold, lambda: self.now, NativeIds())

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None
        key, phase, _entry = found
        if phase == "admitted":
            return super().launch(backlog, task_id, minutes)
        recovery, attempts = self.recovery(), self.attempts()
        authorized = RecoveryLaunch(recovery)(key, OWNER, self.now + minutes * 60)
        assert authorized.outcome is Outcome.AUTHORIZED and authorized.intent is not None
        result = Continuation(recovery, attempts, NativeContinuation(attempts, recovery.store))(
            key, OWNER, intent=authorized.intent,
        )
        assert result.state is State.COMPLETED, result
        return Launched(key, (OWNER.pid, OWNER.start, OWNER.boot))

    def releaser(self) -> SlotRelease:
        return replace(super().releaser(),
                       observe=lambda entry: "matching" if self.effects.processes.states.get(entry[0]) is Seen.ALIVE
                       else "unknown" if self.effects.processes.states.get(entry[0]) is Seen.UNKNOWN else "gone",
                       setup_seen=lambda identity: self.effects.processes.states.get(identity.pid, Seen.GONE).value)

    def install_hooks(self) -> None:
        verify, release, publish = Verifier.verify, SlotRelease.release, BranchPublish.publish

        def verified(app: Verifier, key: AttemptKey) -> VerifyResult:
            result = verify(app, key)
            self.effects.after("verify")
            return result

        def released(app: SlotRelease, key: AttemptKey, abandon: bool, me: tuple[int, str, str] | None = None) -> ReleaseResult:
            result = release(app, key, abandon, me)
            self.effects.after("release")
            return result

        def published(app: BranchPublish, key: AttemptKey) -> PublishResult:
            result = publish(app, key)
            self.effects.after("publish")
            return result

        self.patch.setattr(Verifier, "verify", verified)
        self.patch.setattr(SlotRelease, "release", released)
        self.patch.setattr(BranchPublish, "publish", published)

    def ports(self) -> RoundPorts:
        ports = super().ports()
        reads = replace(ports.reads, recovery=self.recovery().status)
        completion = CapturedCompletion(self.attempts(), HoldStore(lambda: self.con), hold, lambda _entry: "gone")
        return replace(ports, reads=reads, holding=self.holding(reads), completion=completion)

    def reopen(self) -> RestartFactory:
        self.con.close()
        return RestartFactory(connect(self.tmp / "factory.db"), self.tmp, self.slot, self.checkouts, self.files,
                              self.tracker, self.effects, self.patch, adopted=True)
