"""What a repeat runs and how the step is judged: the next attempt dispatches from a dirty slot at E (where the previous
attempt ended) as a fresh session, is verified by the same operation, and the verdict covers the whole chain from
attempt 1's B, each commit held to its own attempt's paths; a verify of a superseded attempt never writes Git. Real
SQLite, the owning agent fake (one per attempt), the semantic Git fake and the fake slot file port."""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from doubles import FakeSlotFiles, RegisteringLauncher, main_at
from git_porcelain import Dirty, Recorded
from git_porcelain.testing import FakeRepo, FakeWorktree
from plan_fixtures import PLAN_TEXT, PLAN_V2
from sqlite_store import begin_immediate

from taskloop.admit import Admitted
from taskloop.admit_chain import ChainAdmission, RepeatRequest
from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_entry import shown
from taskloop.attempt_status import StatusPorts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    AttemptKey,
    ChainLink,
    Checkouts,
    Effect,
    EntryIdentity,
    FileRef,
    FileStat,
    Rejected,
    SlotFiles,
    StepRules,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.operations import (
    Failed,
    Started,
)
from taskloop.repeat import StepRepeat
from taskloop.slot_lock import hold, repeating
from taskloop.steps import kind
from taskloop.verdict import judge
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
STEP = kind("plan")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
D = "docs/design/tl-1/"
NOTE = D + "note.md"
STRAY = "scratch.txt"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}
UNCHANGED = {"disposition": "unchanged", "plan_path": P, "paths": [], "message": None, "explanation": "Still valid"}
TASK = "Plan the actual task"
type Files = Mapping[str, str]


def head(slot: FakeWorktree) -> str:
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


def commit(slot: FakeWorktree, files: Files, message: str = "step") -> str:
    for path, text in files.items():
        slot.write_file(path, text)
    assert isinstance(slot.record(message, paths="all"), Recorded)
    return head(slot)


class Agent:
    """One attempt's run: the 'agent' writes and removes files in the slot (never Git), then answers; one FakeRun each."""

    def __init__(self, slot: FakeWorktree, written: Files, answer: Mapping[str, object], removed: Sequence[str] = ()) -> None:
        self.slot, self.written, self.answer, self.removed = slot, written, answer, removed
        self.specs: list[LaunchSpec] = []

    def __call__(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.specs.append(spec)
        for path, text in self.written.items():
            self.slot.write_file(path, text)
        for path in self.removed:
            self.slot.remove_file(path)
        text = json.dumps(self.answer)
        return FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)


class Step:
    """One task's step over the in-memory factory.db: run an attempt, verify it, repeat it."""

    def __init__(self, con: sqlite3.Connection, tmp: Path, slot: FakeWorktree, checkouts: Checkouts, files: SlotFiles) -> None:
        self.con, self.tmp, self.slot, self.checkouts, self.files = con, tmp, slot, checkouts, files
        self.store = AttemptStore(lambda: con)
        self.launcher = RegisteringLauncher(self.store)
        self.verifier = Verifier(self.store, checkouts, files, lambda _worker: True, lambda: 20, hold, ids=NativeIds())

    def run(self, key: AttemptKey, entry: EntryIdentity, agent: Agent) -> str:
        attempts = Attempts(
            self.store,
            EvidenceFiles(self.tmp),
            AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()),
            agent,
            lambda: 10,
            self.checkouts,
            self.files,
        )
        found = attempts.execute(key, entry)
        return f"{found.status} {found.reason}"

    def admission(self) -> ChainAdmission:
        return ChainAdmission(lambda: self.con, begin_immediate, EvidenceFiles(self.tmp), lambda: 10, ids=NativeIds())

    def repeat(self, current: AttemptKey) -> Started | Failed:
        found = self.store.attempt_of("tasks", "tl-1")
        assert found is not None and found[0] == current
        repeat = StepRepeat(self.store, self.verifier, EvidenceFiles(self.tmp), self.admission(), self.launcher, lambda _worker: True,
                            lambda _entry: "gone", lambda: 10, repeating, ids=NativeIds())
        return repeat.repeat("tasks", "tl-1", current, found[2], 30)

    def next_attempt(self, current: AttemptKey) -> tuple[AttemptKey, EntryIdentity]:
        started = self.repeat(current)
        assert isinstance(started, Started) and started.status == "repeated" and started.entry is not None
        return self.launcher.calls[-1], started.entry

    def input(self, key: AttemptKey) -> str:
        record = self.store.load(key)
        assert record is not None
        return EvidenceFiles(self.tmp).read(record.admission.input_ref)


@pytest.fixture
def step(registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles) -> Step:
    return Step(registered, tmp_path, slot, checkouts, slot_files)


def made(slot: FakeWorktree, base: str) -> list[str]:
    return [entry.subject for entry in slot.repo.history([head(slot)], not_on=[base])]


def test_the_next_attempt_dispatches_at_e_with_the_leftovers_as_a_fresh_session_and_verifies_the_chain(
    step: Step, slot: FakeWorktree
) -> None:
    base = head(slot)
    assert step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN)) == "pending verification"
    assert shown(step.verifier.verify(KEY)) == "unsettled:uncommitted"
    x1 = head(slot)
    key, entry = step.next_attempt(KEY)
    second = Agent(slot, {}, UNCHANGED, removed=[STRAY])
    assert step.run(key, entry, second) == "pending verification"
    record = step.store.load(key)
    assert record is not None and record.base_commit == x1 == record.start  # dispatched from the dirty slot at E
    (spec,) = second.specs
    assert "resume" not in spec.argv and spec.argv[1] == "exec"  # a fresh session, never a resumed one
    assert f"?? {STRAY}" in spec.stdin + " ".join(spec.argv) and TASK in spec.stdin + " ".join(spec.argv)
    found = step.verifier.verify(key)
    assert isinstance(found, Verified) and not found.reused  # X1, then `unchanged`: verified, not reused
    assert made(slot, base) == ["Plan tl-1"] and slot.dirty().raw is False


def test_a_second_commit_on_the_first_is_verified_with_each_held_to_its_own_paths(step: Step, slot: FakeWorktree) -> None:
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, NOTE: "n"}, PLAN))
    assert shown(step.verifier.verify(KEY)) == "unsettled:uncommitted"
    key, entry = step.next_attempt(KEY)
    step.run(key, entry, Agent(slot, {P: PLAN_V2}, PLAN | {"paths": [P, NOTE]}))
    found = step.verifier.verify(key)
    assert isinstance(found, Verified) and not found.reused
    assert made(slot, base) == ["Plan tl-1", "Plan tl-1"]
    rows = step.con.execute("SELECT number,base_commit,end_commit FROM attempt ORDER BY number").fetchall()
    assert rows[0][1] == base and rows[1][1] == rows[0][2] and rows[1][2] == head(slot)
    assert step.con.execute("SELECT attempt_id,verdict FROM verification").fetchall() == [(key.attempt_id, "verified")]


def test_planned_with_nothing_new_in_a_later_attempt_is_rejected_for_good(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    key, entry = step.next_attempt(KEY)
    step.run(key, entry, Agent(slot, {}, PLAN, removed=[STRAY]))
    assert step.verifier.verify(key) == Rejected("nothing_written")


@pytest.mark.parametrize(("move", "word"), [("commit", "head_moved"), ("branch", "branch"), ("detached", "detached")])
def test_a_slot_not_at_e_refuses_dispatch_and_the_attempt_stays_admitted(step: Step, slot: FakeWorktree, move: str, word: str) -> None:
    """A repeat dispatches only on its task branch at E: never a commit elsewhere, another branch or a detached HEAD."""
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    key, entry = step.next_attempt(KEY)
    if move == "commit":
        commit(slot, {"README": "two"}, "someone else")
    elif move == "branch":
        slot.checkout_new("other")
    else:
        slot.park("HEAD")
    agent = Agent(slot, {}, UNCHANGED)
    assert step.run(key, entry, agent) == f"refused slot_{word}"
    assert agent.specs == [] and step.store.attempt_of("tasks", "tl-1") == (key, "admitted", entry)


def test_three_attempts_then_the_owner(step: Step, slot: FakeWorktree, tmp_path: Path) -> None:
    """Each repeat's input is its own feedback over attempt 1's task, never an earlier feedback nested; the third
    unsettled attempt is `repeats_exhausted`, shown and refused, nothing admitted."""
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    second, entry = step.next_attempt(KEY)
    step.run(second, entry, Agent(slot, {}, UNCHANGED))
    reads = StatusPorts(step.store, lambda _entry: "gone", lambda: 10, step.verifier.leftovers, lambda: "boot")
    shown_two = show_attempt(reads, tmp_path / "art", "tasks", "tl-1")
    assert not isinstance(shown_two, Failed) and (shown_two.view.number, shown_two.view.next) == (2, "repeat")
    third, entry = step.next_attempt(second)
    text = step.input(third)
    assert text.startswith(
        "Your final message must be the JSON answer only; write plan.md before you answer `planned`; "
        "a message without a tool call ends the step.\n\nFirst assess depth from the supplied task text alone"
    )
    assert text.index("First assess depth") < text.index("Attempt 2 of this step")
    assert text.count("BEGIN SLOT STATUS") == 1 and text.endswith(TASK)
    step.run(third, entry, Agent(slot, {}, UNCHANGED))
    shown_three = show_attempt(reads, tmp_path / "art", "tasks", "tl-1")
    assert not isinstance(shown_three, Failed)
    each = shown_three.view
    assert (each.number, each.next, each.result.reason, each.leftovers) == (3, "repeats_exhausted", "repeats_exhausted",
                                                                             ("uncommitted", f"?? {STRAY}"))
    assert [attempt_id for attempt_id, _reason in each.earlier] == [second.attempt_id, "attempt"]
    assert step.repeat(third) == Failed("refused", "repeats_exhausted")
    assert step.con.execute("SELECT count(*) FROM attempt").fetchone() == (3,)
    slot.remove_file(STRAY)
    assert isinstance(step.verifier.verify(third), Verified)  # the owner tidies the slot; attempt 3 can still verify


def test_a_late_verify_of_a_superseded_attempt_writes_no_git(step: Step, slot: FakeWorktree) -> None:
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT}, PLAN))
    taken = step.admission().admit_repeat(RepeatRequest(KEY, "feedback", 1000, "uncommitted"))
    assert isinstance(taken, Admitted)
    assert step.verifier.verify(KEY) == VerifyRefused("stale_reservation") and made(slot, base) == []


def test_a_takeover_during_the_verify_is_superseded_before_any_git_write(
    step: Step, slot: FakeWorktree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P was loaded before the handoff; the takeover lands during its pre-commit status read: nothing is staged."""
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT}, PLAN))
    index, read = dict(slot.state().index), FakeWorktree.dirty

    def dirty(self: FakeWorktree, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        if ignored_under:
            assert isinstance(step.admission().admit_repeat(RepeatRequest(KEY, "feedback", 1000, "uncommitted")), Admitted)
        return read(self, base, ignored_under=ignored_under)

    monkeypatch.setattr(FakeWorktree, "dirty", dirty)
    assert step.verifier.verify(KEY) == Unsettled("superseded")
    assert slot.state().index == index and made(slot, base) == []
    assert step.con.execute("SELECT end_commit FROM attempt WHERE attempt_id='attempt'").fetchone() == (None,)
    assert step.con.execute("SELECT count(*) FROM verification").fetchone() == (0,)


@pytest.mark.parametrize(("before", "written", "expected"), [
    (None, {P: PLAN_TEXT, ".gitattributes": "* filter=x\n"}, Unsettled("unsafe", (".gitattributes",))),
    ({".gitignore": "*.log\n"}, {P: PLAN_TEXT, D + "x.log": "x"}, Unsettled("ignored", (D + "x.log",))),
], ids=["git_file", "ignored"])
def test_show_judges_leftovers_before_the_commit_as_the_verify_does(
    step: Step, slot: FakeWorktree, before: Files | None, written: Files, expected: Unsettled
) -> None:
    if before is not None:
        commit(slot, before)
        main_at(slot)
    step.run(KEY, ENTRY, Agent(slot, written, PLAN))
    assert step.verifier.leftovers(KEY) == expected == step.verifier.verify(KEY)


def rules() -> StepRules:
    return StepRules(D)


def attempt(number: int, base: str, end_commit: str | None, paths: tuple[str, ...], effect: Effect = "commit") -> ChainLink:
    return ChainLink(number, base, end_commit, effect, paths, FileRef("input.txt", "d"))


def test_judge_holds_each_commit_of_the_chain_to_its_own_attempts_paths(repo: FakeRepo, slot: FakeWorktree) -> None:
    base = head(slot)
    x1 = commit(slot, {P: PLAN_TEXT, NOTE: "n"})
    x2 = commit(slot, {NOTE: "changed"})
    first = attempt(1, base, x1, (P, NOTE))
    assert isinstance(judge(repo, repo.path, x2, STEP, rules(), (first, attempt(2, x1, None, (P, NOTE)))), Verified)
    assert judge(repo, repo.path, x2, STEP, rules(), (first, attempt(2, x1, None, (P,)))) == Rejected("paths")
    assert judge(repo, repo.path, x2, STEP, rules(), (attempt(1, base, x1, (P,)), attempt(2, x1, None, (P, NOTE)))) == Rejected("paths")
    unchanged = judge(repo, repo.path, x1, STEP, rules(), (first, attempt(2, x1, x1, (), "keep")))
    assert isinstance(unchanged, Verified) and not unchanged.reused


def test_judge_refuses_a_foreign_commit_inside_the_chain(repo: FakeRepo, slot: FakeWorktree) -> None:
    base = head(slot)
    x1 = commit(slot, {P: PLAN_TEXT})
    commit(slot, {"README": "two"}, "someone else")
    x2 = commit(slot, {P: PLAN_V2})
    chain = (attempt(1, base, x1, (P,)), attempt(2, x1, None, (P,)))
    assert judge(repo, repo.path, x2, STEP, rules(), chain) == Rejected("chain_length")
    assert judge(repo, repo.path, x2, STEP, rules(), (attempt(1, base, None, (P,)), attempt(2, x1, None, (P,)))) == Rejected("chain_length")
    reused = judge(repo, repo.path, base, STEP, rules(), (attempt(1, base, base, (), "keep"),))
    assert reused == Rejected("plan_missing")  # no commit in the whole step: only the plan rules at B1


@pytest.mark.parametrize("reason", ["unsafe", "ignored"])
def test_after_an_attempt_that_committed_nothing_the_repeat_lists_every_file_again_and_verifies(
    step: Step, slot: FakeWorktree, slot_files: FakeSlotFiles, reason: str
) -> None:
    """Nothing of attempt 1 was committed (E is B): its feedback asks for `planned` with every file again, and an
    attempt that does so verifies; an `unchanged` would only leave the plan uncommitted."""
    stray = D + "x.log"
    if reason == "ignored":
        commit(slot, {".gitignore": "*.log\n"})
        main_at(slot)
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, **({stray: "x"} if reason == "ignored" else {})}, PLAN))
    if reason == "unsafe":
        slot_files.entries[slot.path / P] = FileStat("file", 7, True)
    assert shown(step.verifier.verify(KEY)) == f"unsettled:{reason}"
    key, entry = step.next_attempt(KEY)
    assert "Nothing of attempt 1 was committed" in step.input(key) and "answer `unchanged`" not in step.input(key)
    slot_files.entries.clear()  # the agent made the plan a plain file again
    step.run(key, entry, Agent(slot, {}, PLAN, removed=[stray] if reason == "ignored" else []))
    record = step.store.load(key)
    assert record is not None and record.base_commit == base == record.start
    assert isinstance(step.verifier.verify(key), Verified) and made(slot, base) == ["Plan tl-1"]


def test_the_true_count_of_leftovers_reaches_the_next_attempt(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT} | {f"stray-{n:02}": "s" for n in range(53)}, PLAN))
    found = step.verifier.verify(KEY)
    assert isinstance(found, Unsettled) and len(found.listing) == 51 and found.listing[-1] == "+3 more"
    key, _entry = step.next_attempt(KEY)
    text = step.input(key)
    assert "\n".join(found.listing) in text and text.count("+3 more") == 1 and "+1 more" not in text


EVIL = D + "e\x1b]0;owned\x07\x9b31m.md"


@pytest.mark.parametrize("reason", ["unsafe", "ignored"])
def test_show_prints_no_control_character_and_a_bounded_listing(
    step: Step, slot: FakeWorktree, slot_files: FakeSlotFiles, tmp_path: Path, reason: str
) -> None:
    if reason == "ignored":
        commit(slot, {".gitignore": "*.md\n!plan.md\n"})
        main_at(slot)
        written = {P: PLAN_TEXT, EVIL: "x"} | {f"{D}n{n:04}.md": "x" for n in range(1000)}
        step.run(KEY, ENTRY, Agent(slot, written, PLAN))
    else:
        step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, EVIL: "x"}, PLAN | {"paths": [P, EVIL]}))
        slot_files.entries[slot.path / EVIL] = FileStat("file", 1, True)
    reads = StatusPorts(step.store, lambda _entry: "gone", lambda: 10, step.verifier.leftovers, lambda: "boot")
    shown_now = show_attempt(reads, tmp_path / "art", "tasks", "tl-1")
    assert not isinstance(shown_now, Failed)
    left = shown_now.view.leftovers
    assert left[0] == reason and not any(ord(c) < 32 or 127 <= ord(c) < 160 for line in left for c in line)
    if reason == "ignored":
        assert len(left) == 52 and left[-1] == "+951 more"
    else:
        assert json.dumps(EVIL, ensure_ascii=True) in left[1] and "execute bit" in left[1]
        assert left[2:] == ("docs/design/tl-1/e?]0;owned??31m.md",)


def test_a_staged_index_at_e_never_dispatches(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    key, entry = step.next_attempt(KEY)
    slot.stage([STRAY], literal=True)  # a person staged the scratch file: the factory's record would sweep it in
    agent = Agent(slot, {}, UNCHANGED, removed=[STRAY])
    assert step.run(key, entry, agent) == "refused slot_staged" and agent.specs == []


def test_a_superseded_verify_that_staged_leaves_the_next_attempt_undispatched(
    step: Step, slot: FakeWorktree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The takeover lands after P's verify staged its paths (the second fence then stops it): N refuses to dispatch on
    that index rather than commit P's staged plan as its own."""
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT}, PLAN))
    stage = FakeWorktree.stage

    def staging(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        stage(self, paths, literal=literal)
        assert isinstance(step.admission().admit_repeat(RepeatRequest(KEY, "feedback", 1000, "uncommitted")), Admitted)

    monkeypatch.setattr(FakeWorktree, "stage", staging)
    assert step.verifier.verify(KEY) == Unsettled("superseded") and made(slot, base) == []
    monkeypatch.setattr(FakeWorktree, "stage", stage)
    found = step.store.attempt_of("tasks", "tl-1")
    assert found is not None and step.store.register_entry(found[0], (9, "s", "boot"), 10) == "accepted"
    assert step.run(found[0], (9, "s", "boot"), Agent(slot, {}, UNCHANGED)) == "refused slot_staged"


def test_a_path_staged_beside_the_listed_ones_is_never_committed(
    step: Step, slot: FakeWorktree, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    stage = FakeWorktree.stage

    def staging(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        stage(self, [*paths, STRAY], literal=literal)  # someone stages the scratch file in between

    monkeypatch.setattr(FakeWorktree, "stage", staging)
    assert step.verifier.verify(KEY) == Unsettled("staged", (STRAY,)) and made(slot, base) == []
    assert step.con.execute("SELECT count(*) FROM verification").fetchone() == (0,)


def test_a_start_that_lost_the_takeover_launches_the_winner(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    taken = step.admission().admit_repeat(RepeatRequest(KEY, "feedback", 1000, "uncommitted"))
    assert isinstance(taken, Admitted)
    repeat = StepRepeat(step.store, step.verifier, EvidenceFiles(step.tmp), step.admission(), step.launcher, lambda _worker: True,
                        lambda _entry: "gone", lambda: 10, repeating, ids=NativeIds())
    found = repeat.repeat("tasks", "tl-1", KEY, ENTRY, 30)  # its read of the current attempt predates the takeover
    assert found == Started("relaunched", "tasks", "tl-1", taken.key.attempt_id, True, (8, "start", "boot"))
    assert step.con.execute("SELECT count(*) FROM attempt").fetchone() == (2,)


def test_a_takeover_during_the_repeats_verify_launches_the_winner(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    taken: list[AttemptKey] = []

    class Racing:
        def verify(self, key: AttemptKey) -> VerifyResult:
            won = step.admission().admit_repeat(RepeatRequest(KEY, "feedback", 1000, "uncommitted"))
            assert isinstance(won, Admitted)
            taken.append(won.key)
            return step.verifier.verify(key)

        def staged(self, key: AttemptKey) -> tuple[str, ...] | None:
            return step.verifier.staged(key)

    repeat = StepRepeat(step.store, Racing(), EvidenceFiles(step.tmp), step.admission(), step.launcher, lambda _worker: True,
                        lambda _entry: "gone", lambda: 10, repeating, ids=NativeIds())
    assert repeat.repeat("tasks", "tl-1", KEY, ENTRY, 30) == Started("relaunched", "tasks", "tl-1", taken[0].attempt_id, True,
                                                                      (8, "start", "boot"))


def test_judge_refuses_a_chain_whose_commit_does_not_sit_on_the_stored_one(repo: FakeRepo, slot: FakeWorktree) -> None:
    """The count from B1 matches, but X2's first parent is not the stored X1 (a side commit took its place)."""
    base = head(slot)
    side = commit(slot, {P: PLAN_TEXT})
    slot.checkout(base)
    commit(slot, {P: PLAN_TEXT}, "other")
    x2 = commit(slot, {P: PLAN_V2})
    chain = (attempt(1, base, side, (P,)), attempt(2, side, None, (P,)))
    assert judge(repo, repo.path, x2, STEP, rules(), chain) == Rejected("not_descendant")


def test_a_staged_slot_is_refused_before_the_takeover_and_nothing_is_spent(step: Step, slot: FakeWorktree) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    slot.stage([STRAY], literal=True)  # the owner's staged file must never become the agent's leftover
    dirs = sorted(path.name for path in (step.tmp / "attempts").iterdir())
    assert step.repeat(KEY) == Failed("unsettled", "staged", STRAY) and step.launcher.calls == []
    assert step.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert step.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == ("attempt", 1)
    assert sorted(path.name for path in (step.tmp / "attempts").iterdir()) == dirs  # no input written


def test_a_file_staged_by_a_person_alone_is_staged_never_committed(step: Step, slot: FakeWorktree) -> None:
    base = head(slot)
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT}, PLAN))
    slot.write_file(STRAY, "s")
    slot.stage([STRAY], literal=True)
    assert step.verifier.verify(KEY) == Unsettled("staged", (STRAY,)) and made(slot, base) == []


def test_show_says_why_an_admitted_attempts_entry_gave_up(step: Step, slot: FakeWorktree, tmp_path: Path) -> None:
    step.run(KEY, ENTRY, Agent(slot, {P: PLAN_TEXT, STRAY: "s"}, PLAN))
    step.verifier.verify(KEY)
    key, _entry = step.next_attempt(KEY)
    log = EvidenceFiles(tmp_path).entry_log(key)
    log.write_text("refused slot_staged verify=refused:not_captured\nTraceback \x1b]0;owned\x07 (most recent call last)\n")
    reads = StatusPorts(step.store, lambda _entry: "gone", lambda: 10, step.verifier.leftovers, lambda: "boot")
    found = show_attempt(reads, tmp_path, "tasks", "tl-1")
    assert not isinstance(found, Failed)
    assert (found.view.phase, found.view.next, found.view.last_entry) == (
        "admitted", "start", "refused slot_staged verify=refused:not_captured")
