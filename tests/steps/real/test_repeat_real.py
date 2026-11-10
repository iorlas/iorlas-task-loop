"""Real layer, one wiring row of a repeat on the real Git adapter: attempt 1 leaves an uncommitted file after the
factory's commit X1, the next attempt takes the reservation over, dispatches from the dirty linked worktree at X1, the
factory commits X2 on X1 (real `record(paths="staged")`), and the chain verdict holds with real `relate` and `sha^` reads.
It also pins the semantic fake's behaviour the unit rows rely on. Set-up runs through `git_porcelain.testing`'s runner."""

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from sqlite_store import begin_immediate

from taskloop.admit import AttemptAdmission
from taskloop.attempt import Attempts, Execution
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Unsettled, Verified
from taskloop.composition import RealSlotFiles, checkouts
from taskloop.evidence_files import EvidenceFiles
from taskloop.launch import Launched, LaunchResult
from taskloop.operations import Started
from taskloop.repeat import StepRepeat
from taskloop.slot_lock import hold, repeating
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
SECOND = (8, "second-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
TASK = "Plan the actual task"


def agent(slot: Path, written: Mapping[str, str], removed: Sequence[str], paths: Sequence[str]) -> Execution:
    answer = {"disposition": "planned", "plan_path": P, "paths": list(paths), "message": "Plan tl-1", "explanation": "done"}

    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        for path, text in written.items():
            (slot / path).parent.mkdir(parents=True, exist_ok=True)
            (slot / path).write_text(text)
        for path in removed:
            (slot / path).unlink()
        text = json.dumps(answer)
        return FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)

    return call


def never(*_args: object) -> NoReturn:
    raise AssertionError("a repeat reads no tracker and claims nothing")


class Launches:
    def __init__(self, store: AttemptStore) -> None:
        self.store = store

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None and self.store.register_entry(found[0], SECOND, 10) == "accepted"
        return Launched(found[0], SECOND)


def test_a_repeat_commits_x2_on_x1_from_the_dirty_worktree_and_the_chain_verifies(
    tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main, slot, art = root / "repo", root / "slots" / "s1", root / "art"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    git(main, "add", "README")
    git(main, "commit", "-q", "-m", "base")
    git(main, "worktree", "add", "-q", "-b", "task/tl-1", str(slot), "HEAD")
    base = git(slot, "rev-parse", "HEAD").strip()
    with begin_immediate(factory):
        factory.execute("INSERT INTO reservation VALUES ('s1',?,?,1,'attempt')", (checkouts(main).identity().key, str(slot)))
        factory.execute(
            """INSERT INTO plan_attempt (attempt_id,dispatch_token,generation,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
            input_digest,schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high','workspace-write',100,
            7,'entry-start','boot',1,1,?)""",
            (checkouts(main).identity().key, hashlib.sha256(TASK.encode()).hexdigest(), base),
        )
    art.mkdir()
    (art / "input.txt").write_text(TASK)
    store, files = AttemptStore(lambda: factory), RealSlotFiles()

    def attempts(run: Execution) -> Attempts:
        return Attempts(store, EvidenceFiles(art), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts, files)

    verifier = Verifier(store, checkouts, files, lambda _worker: True, lambda: 20, hold)
    assert attempts(agent(slot, {P: "# Plan\n", "scratch.txt": "s"}, (), [P])).execute(KEY, ENTRY).reason == "verification"
    assert verifier.verify(KEY) == Unsettled("uncommitted", ("?? scratch.txt",))
    x1 = git(slot, "rev-parse", "HEAD").strip()
    admission = AttemptAdmission(lambda: factory, begin_immediate, EvidenceFiles(art), never, never, never, never, lambda: 10, never)
    repeat = StepRepeat(store, verifier, EvidenceFiles(art), admission, Launches(store), lambda _w: True, lambda _e: "gone", lambda: 10,
                        repeating)
    started = repeat.repeat("tasks", "tl-1", KEY, ENTRY, 30)
    assert isinstance(started, Started) and started.status == "repeated"
    found = store.attempt_of("tasks", "tl-1")
    assert found is not None
    second = agent(slot, {P: "# Plan v2\n"}, ("scratch.txt",), [P])
    assert attempts(second).execute(found[0], SECOND).reason == "verification"
    verdict = verifier.verify(found[0])
    assert isinstance(verdict, Verified) and not verdict.reused
    assert git(slot, "rev-parse", "HEAD^").strip() == x1 and git(slot, "rev-parse", "HEAD^^").strip() == base
    assert git(slot, "status", "--porcelain").strip() == ""
    assert git(slot, "log", "-1", "--format=%B").strip().endswith(f"Task-Loop-Attempt: {found[0].attempt_id}")
