"""The one recovery after `refused:conflict` (tl-8bh9.14.8 section 13; `land_guide.restart`): the person brings `main` up to
date, sets the stale `task/<id>` aside under a name of its own (locally; origin's is deleted), abandons through the real
`release_task` (a passed checks attempt present) and restarts; the restarted chain is made on the current `main`, so its
commit lands. Two benches: the land's (`land_bench`: the abandon, the clean land, a second conflict and its own recovery)
and the rounds' (`round_bench`: the restart's plan and implement start at the moved `main`)."""

import sqlite3
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain import Recorded, Sha
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from land_bench import REQUIRED, LandBench, bench
from plan_fixtures import PLAN_TEXT
from round_bench import Factory, Tracker, scripted, task
from sqlite_store import begin_immediate

from taskloop import check_store
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, SlotFiles
from taskloop.check_release import ChecksRelease
from taskloop.ids import NativeIds
from taskloop.land import Landed
from taskloop.land_guide import restart
from taskloop.operations import Failed, ReleasedTask, release_task
from taskloop.slot_lock import custody
from taskloop.slot_release import SlotRelease


def abandon(b: LandBench) -> ReleasedTask | Failed:
    """`tl step release tl-1 --abandon`: the real operation, the real checks and implement releases."""
    work = b.checking()
    checks = ChecksRelease(work.store, work.checkouts, work.slot_files, lambda _entry: "gone", b.ports().custody, work.clock, work.seen,
                           work.scratch, ids=NativeIds())
    store = AttemptStore(lambda: b.con)
    implement = SlotRelease(store, b.views, b.files, lambda _entry: "gone", lambda _worker: True, custody, lambda _root, _task: True,
                            lambda: b.now, lambda _setup: "gone", lambda _scratch: True, ids=NativeIds())
    return release_task(store, implement, checks, "tasks", "tl-1", abandon=True)


def seed_chain(b: LandBench, number: int, x: str) -> None:
    """The restarted chain's done implement attempt (X on `task/tl-1`, published) and its passed, released checks attempt."""
    base, repo_id, implement, checks = b.origin_main(), b.repo.identity().key, f"implement{number}", f"checks{number}"
    with begin_immediate(b.con):
        b.con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,phase,base_commit,end_commit,number,seq,slot_head,
            after_commit) VALUES (?,?,1,'implement','beads','tasks','tl-1','/tracker',?,'s0','input.txt','digest',1,'m','e',
            '{"harness":"codex","sandbox":"workspace-write"}',100,'captured',?,?,1,?,?,?)""", (implement,
            f"{implement}-token", repo_id, base, x, 2 * number, b.d, base))
        b.con.execute(
            """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,
            stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,effect,session_state)
            VALUES (?,?,1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','commit','complete')""", (implement, f"{implement}-token"))
        b.con.execute("INSERT INTO verification (attempt_id,dispatch_token,generation,verdict,observed_at) "
                      "VALUES (?,?,1,'verified',5)", (implement, f"{implement}-token"))
        b.con.execute("INSERT INTO slot_release VALUES (?,?,1,?,4,'kept')", (implement, f"{implement}-token", b.d))
        b.con.execute("INSERT INTO published_branch VALUES (?,?,1,?,?,6)", (implement, f"{implement}-token", x, x))
        key = AttemptKey(checks, f"{checks}-token", 1)
        check_store.insert(b.con, check_store.ChecksAdmitted(key, implement, 1, "s1", b.d, base, REQUIRED, 100.0))
        b.con.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=? "
                      "WHERE attempt_id=?", (b.d, checks))


def recover(b: LandBench, number: int, old_x: str, files: dict[str, str]) -> str:
    """What the guide says, then what the restart's agents leave: X on a new `task/tl-1` at the current main."""
    person, aside = b.repo.worktree(b.repo.identity().root), f"old/tl-1-{old_x[:12]}"
    b.repo.fetch()
    person.merge_ff("origin/main")  # git pull --ff-only
    b.repo.rename_branch("task/tl-1", aside)  # git branch -m
    b.repo.delete_remote_at("origin", "refs/heads/task/tl-1", Sha(old_x))  # git push origin --delete
    assert isinstance(abandon(b), ReleasedTask)
    person.checkout_new("task/tl-1", "main")  # the restarted entry's `take_branch` at the local main
    for path, text in files.items():
        person.write_file(path, text)
    made = person.record("the restarted task's commit", paths="all")
    assert isinstance(made, Recorded)
    person.push("task/tl-1", remote="origin", head=made.sha)
    person.checkout("main")
    seed_chain(b, number, made.sha)
    return made.sha


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def test_the_guide_names_real_commands_and_an_aside_no_earlier_recovery_used() -> None:
    first, second = restart("tl-1", "a" * 40), restart("tl-1", "b" * 40)
    assert "git branch -m task/tl-1 old/tl-1-" + "a" * 12 in first and "old/tl-1-" + "a" * 12 not in second
    assert "git push origin --delete task/tl-1" in first and "stay only in your checkout" in first and "cannot fast-forward" in first
    assert "tl step release tl-1 --abandon" in first and "tl step start tl-1" in first


def test_manual_recovery_after_a_read_only_conflict_is_restarted_abandoned_and_lands(b: LandBench) -> None:
    b.advance({"src/x.py": "X = 2\n"})
    found = b.land(no_change=True)
    assert isinstance(found, Failed) and found.word == "refused:conflict" and b.conflict_runs == []
    x2 = recover(b, 2, b.x, {"src/x.py": "X = 2\nY = 1\n"})
    landed = b.land()
    assert isinstance(landed, Landed) and b.files_of(b.origin_main())["src/x.py"] == "X = 2\nY = 1\n"
    assert x2 != b.x and b.repo.pushes >= 1


def test_a_second_conflict_has_a_working_recovery_with_its_own_aside_name(b: LandBench) -> None:
    b.advance({"src/x.py": "X = 2\n"})
    x2 = recover(b, 2, b.x, {"src/x.py": "X = 2\nY = 1\n"})
    b.advance({"src/x.py": "X = 3\n"}, "main moves again")
    again = b.land(no_change=True)
    assert isinstance(again, Failed) and again.word == "refused:conflict" and b.conflict_runs == []
    recover(b, 3, x2, {"src/x.py": "X = 3\nZ = 1\n"})
    assert isinstance(b.land(), Landed)
    assert {name for name, _sha in b.repo.branches("old/")} == {f"old/tl-1-{b.x[:12]}", f"old/tl-1-{x2[:12]}"}


@pytest.fixture
def remote() -> FakeRemote:
    made = FakeRemote("https://example.invalid/repo.git")
    made.advance("main", {"README": "one", ".task-loop.json": "{}"})
    return made


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def factory(factory: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Factory:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    plan, code = "docs/design/tl-1/plan.md", "src/shared.py"
    built.agents["tl-1", "plan"] = scripted(
        slot.repo, {"disposition": "planned", "plan_path": plan, "paths": [plan], "message": "Plan", "explanation": "planned"},
        {plan: PLAN_TEXT})
    built.agents["tl-1", "implement"] = scripted(
        slot.repo, {"disposition": "implemented", "paths": [code], "message": "Add it", "explanation": "ran just check"},
        {code: "X = 1\n"})
    return built


def test_the_restarted_chain_is_planned_and_implemented_on_the_moved_main(factory: Factory, remote: FakeRemote) -> None:
    for _ in range(4):
        factory.round()
    repo, first = factory.slot.repo, factory.tip("tl-1")
    moved = remote.advance("main", {"src/shared.py": "X = 2\n"}, "someone else lands")
    repo.fetch()
    repo.worktree(repo.path).merge_ff("origin/main")
    repo.rename_branch("task/tl-1", f"old/tl-1-{first[:12]}")
    repo.delete_remote_at("origin", "refs/heads/task/tl-1", Sha(first))
    abandoned = release_task(factory.store, factory.releaser(), factory.checks_release(), "tasks", "tl-1", abandon=True)
    assert isinstance(abandoned, ReleasedTask)
    factory.agents["tl-1", "implement"] = scripted(
        repo, {"disposition": "implemented", "paths": ["src/shared.py"], "message": "Add it", "explanation": "ran just check"},
        {"src/shared.py": "X = 2\nY = 1\n"})
    factory.by_hand("tl-1")  # tl step start
    for _ in range(4):
        factory.round()
    second = factory.tip("tl-1")
    assert second != first and moved in [each.sha for each in repo.history([second])]
