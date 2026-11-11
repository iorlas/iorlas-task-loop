"""The slot setup before an implement agent (S5e-1), through `Attempts.execute` on real SQLite, the semantic Git fake
and the environment fakes of `doubles`: the order of section 4 as observed calls, reuse, every refusal and recovery path,
and that no refusal dispatches the agent."""

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from doubles import Command, Environment, FakeProfiles
from git_porcelain.testing import FakeWorktree

from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, Checkouts, SlotFiles
from taskloop.environment import Renewal, folders, setup_digest
from taskloop.evidence_files import EvidenceFiles
from taskloop.prepare import Prepared
from taskloop.profile import Unavailable

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
UNCHANGED = {"disposition": "unchanged", "paths": [], "message": None, "explanation": "nothing to do"}
ROW = "SELECT run,conclusion,rc,command,pid FROM setup_run ORDER BY run"


@pytest.fixture
def implementing(registered: sqlite3.Connection) -> sqlite3.Connection:
    """The registered attempt as attempt 1 of implement, starting from D (its `after_commit`)."""
    registered.execute("UPDATE attempt SET step='implement',after_commit=slot_head")
    return registered


@pytest.fixture
def environment(implementing: sqlite3.Connection, checkouts: Checkouts, tmp_path: Path) -> Environment:
    return Environment(implementing, checkouts, tmp_path)


@dataclasses.dataclass
class Entry:
    """One entry's execute: the agent records itself in the shared events; `renewals` answer the claim renewal."""

    environment: Environment
    checkouts: Checkouts
    files: SlotFiles
    renewals: list[Renewal] = dataclasses.field(default_factory=list)
    wired: bool = True

    def agent(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.environment.events.append("agent")
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(UNCHANGED), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    def renew(self) -> Renewal:
        self.environment.events.append("renew")
        return self.renewals.pop(0) if self.renewals else "held"

    def execute(self) -> AttemptResult:
        env = self.environment
        attempts = Attempts(AttemptStore(lambda: env.con), EvidenceFiles(env.artifacts), lambda: ("/bin/codex", {"HOME": "/home/p"}),
                            self.agent, env.clock, self.checkouts, self.files, environment=env.preparation() if self.wired else None)
        return attempts.execute(KEY, ENTRY, self.renew)


@pytest.fixture
def entry(environment: Environment, checkouts: Checkouts, slot_files: SlotFiles) -> Entry:
    return Entry(environment, checkouts, slot_files)


def held() -> Renewal:
    return "held"


def rows(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute(ROW).fetchall()


def phase(con: sqlite3.Connection) -> str:
    return con.execute("SELECT phase FROM attempt").fetchone()[0]


def refused(entry: Entry, status: str, reason: str) -> list[str]:
    """Execute once, expect that refusal with nothing dispatched; the events of this execute."""
    events = entry.environment.events
    events.clear()
    result = entry.execute()
    assert (result.status, result.reason) == (status, reason)
    assert "agent" not in events and phase(entry.environment.con) == "admitted"
    return list(events)


def test_attempt_one_runs_the_setup_in_order_then_dispatches(entry: Entry, slot: FakeWorktree, tmp_path: Path) -> None:
    env = entry.environment
    env.profiles = FakeProfiles((("just", "install"), ("just", "bootstrap")))
    seen: list[object] = []
    env.process.script = [Command(effect=lambda: seen.append(rows(env.con))), Command()]
    entry.execute()
    found = folders(slot.path)
    assert env.events == [
        "ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1",
        "empty .env/s1", "ensure s1/uv-cache", "ensure s1/uv-tools",
        "exec just install", "group 501", "exec just bootstrap", "group 502",
        "empty .t/s1", "renew", "agent",
    ]
    assert seen == [[(1, None, None, 0, 501)]]  # the identity was committed before the command executed
    b = env.con.execute("SELECT base_commit FROM attempt").fetchone()[0]
    stored = env.con.execute("SELECT run,commit_sha,digest,command,pgid,proc_start,boot,conclusion,rc FROM setup_run").fetchall()
    assert stored == [(1, b, setup_digest((("just", "install"), ("just", "bootstrap"))), 1, 502, "start-502", "boot", "passed", 0)]
    assert env.profiles.read == [b] and env.profiles.opened == [(slot.path, slot.repo.identity().common_dir / "worktrees" / "s1")]
    call = env.process.calls[0]
    assert (call.cwd, call.timeout) == (str(slot.path), 90)
    assert {key: call.env[key] for key in ("HOME", "TMPDIR", "UV_CACHE_DIR", "UV_TOOL_DIR")} == {
        "HOME": "/home/p", "TMPDIR": str(found.tmp), "UV_CACHE_DIR": str(found.cache), "UV_TOOL_DIR": str(found.tools)}
    assert "UV_OFFLINE" not in call.env
    log = EvidenceFiles(tmp_path).setup_log(KEY, 1).read_text()
    assert log == "$ just install\ndone\nexit 0\n$ just bootstrap\ndone\nexit 0\n"


def test_every_setup_resets_the_slots_ignored_files(entry: Entry, slot: FakeWorktree) -> None:
    """Whatever an earlier agent left ignored in the slot (a plan agent, an abandoned task) is gone before setup runs."""
    slot.repo.exclude_locally([".venv/"])
    slot.write_file(".venv/bin/python", "planted")
    entry.environment.process.script = [Command(effect=lambda: seen.append(slot.read_file(".venv/bin/python")))]
    seen: list[str | None] = []
    entry.execute()
    assert seen == [None] and "agent" in entry.environment.events


def test_a_reset_that_leaves_ignored_files_refuses(entry: Entry, slot: FakeWorktree, monkeypatch: pytest.MonkeyPatch) -> None:
    slot.repo.exclude_locally([".venv/"])
    slot.write_file(".venv/lib.py", "planted")
    monkeypatch.setattr(FakeWorktree, "clean", lambda *_args, **_options: None)
    events = refused(entry, "refused", "environment:reset")
    assert not any(event.startswith("exec") for event in events) and rows(entry.environment.con) == []


def test_a_passed_run_is_reused_by_a_relaunch_of_the_still_admitted_attempt(entry: Entry, slot: FakeWorktree) -> None:
    """The claim is lost after setup: refused before dispatch. The relaunch skips the reset and the commands; files
    written in between stay (no reset), the scratch is still emptied and the claim renewed."""
    entry.renewals = ["lost"]
    assert refused(entry, "refused", "claim_lost")[-1] == "renew"
    slot.repo.exclude_locally([".venv/"])
    slot.write_file(".venv/kept", "from setup")
    entry.environment.events.clear()
    entry.execute()
    assert entry.environment.events == [
        "ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1", "empty .t/s1", "renew", "agent"]
    assert slot.read_file(".venv/kept") == "from setup" and rows(entry.environment.con) == [(1, "passed", 0, 0, 501)]


def test_an_unrenewed_claim_still_dispatches(entry: Entry) -> None:
    entry.renewals = ["unrenewed"]
    entry.execute()
    assert entry.environment.events[-2:] == ["renew", "agent"]


@pytest.mark.parametrize(("commit", "same_setup"), [("e" * 40, True), (None, False)], ids=["other_base", "changed_setup"])
def test_a_passed_run_at_another_base_or_setup_runs_again(entry: Entry, commit: str | None, same_setup: bool) -> None:
    con = entry.environment.con
    d = con.execute("SELECT slot_head FROM attempt").fetchone()[0]
    digest = setup_digest((("just", "bootstrap"),) if same_setup else (("just", "install"),))
    con.execute("""INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion,rc)
                VALUES ('attempt',1,'dispatch',1,?,?,1,2,'passed',0)""", (commit or d, digest))
    entry.execute()
    assert "exec just bootstrap" in entry.environment.events and rows(con)[-1] == (2, "passed", 0, 0, 501)


def test_a_failing_command_stops_the_run_and_two_failures_end_relaunching(entry: Entry) -> None:
    env = entry.environment
    env.profiles = FakeProfiles((("just", "install"), ("just", "bootstrap")))
    env.process.script = [Command(rc=3), Command(rc=1)]
    events = refused(entry, "unavailable", "environment:exit")
    assert [event for event in events if event.startswith("exec")] == ["exec just install"]
    assert EvidenceFiles(env.artifacts).setup_log(KEY, 1).read_text() == "$ just install\ndone\nexit 3\n"
    refused(entry, "unavailable", "environment:exit")  # one transient failure is tolerated: the relaunch runs it again
    assert refused(entry, "refused", "environment:failed") == []  # nothing observed, created, emptied or run
    assert rows(env.con) == [(1, "failed", 3, 0, 501), (2, "failed", 1, 0, 502)]


@pytest.mark.parametrize("command", [Command(rc=None, exec_failed=True), Command(spawn_error=True)], ids=["exec", "spawn"])
def test_a_command_that_never_ran_is_a_failed_run(entry: Entry, command: Command) -> None:
    entry.environment.process.script = [command]
    events = refused(entry, "unavailable", "environment:exit")
    assert not any(event.startswith("group") for event in events)
    assert rows(entry.environment.con)[0][1:3] == ("failed", None)


def test_an_uncertain_start_keeps_its_identity_and_is_reconciled_by_the_next_entry(entry: Entry) -> None:
    """Never signalled: a live or unknown setup refuses with nothing emptied or run; once gone it is `interrupted` and a
    new run starts (an interrupted run is not a failure)."""
    env = entry.environment
    env.process.script = [Command(uncertain=True)]
    refused(entry, "unavailable", "environment:uncertain")
    assert rows(env.con) == [(1, None, None, 0, 501)]
    env.seen[501] = "alive"
    assert refused(entry, "unavailable", "environment:running") == ["seen 501"]
    env.seen[501] = "unknown"
    assert refused(entry, "unavailable", "environment:unknown") == ["seen 501"]
    env.seen[501] = "gone"
    entry.execute()
    assert rows(env.con) == [(1, "interrupted", None, 0, 501), (2, "passed", 0, 0, 502)] and env.events[-1] == "agent"


def test_an_unfinished_run_with_no_registered_command_is_interrupted_unobserved(entry: Entry) -> None:
    con = entry.environment.con
    con.execute("INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at) "
                "VALUES ('attempt',1,'dispatch',1,?,?,1)", ("e" * 40, "f" * 64))
    entry.execute()
    assert not any(event.startswith("seen") for event in entry.environment.events)
    assert [row[:2] for row in rows(con)] == [(1, "interrupted"), (2, "passed")]


def test_a_timed_out_command_and_a_deadline_between_commands_expire(entry: Entry) -> None:
    env = entry.environment
    env.profiles = FakeProfiles((("a",), ("b",)))
    env.process.script = [Command(timed_out=True, rc=None)]
    refused(entry, "refused", "expired")
    now = [10.0]
    env.clock = lambda: now[0]
    env.process.script = [Command(effect=lambda: now.__setitem__(0, 100.0))]
    events = refused(entry, "refused", "expired")
    assert [event for event in events if event.startswith("exec")] == ["exec a"]
    assert [row[:2] for row in rows(env.con)] == [(1, "timed_out"), (2, "timed_out")]


def test_a_lingering_group_after_the_first_of_two_commands_stops_the_run(entry: Entry) -> None:
    env = entry.environment
    env.profiles = FakeProfiles((("a",), ("b",)))
    env.process.script = [Command(lingering=True)]
    events = refused(entry, "unavailable", "environment:lingering")
    assert [event for event in events if event.startswith(("exec", "group"))] == ["exec a", "group 501"]
    assert rows(env.con) == [(1, "lingering", 0, 0, 501)]
    assert EvidenceFiles(env.artifacts).setup_log(KEY, 1).read_text().endswith("exit 0\nlingering\n")


def test_a_slot_left_dirty_by_setup_is_a_failed_run_and_holds_the_slot(entry: Entry, slot: FakeWorktree) -> None:
    entry.environment.process.script = [Command(effect=lambda: slot.write_file("generated.txt", "x"))]
    refused(entry, "refused", "environment:dirty")
    assert rows(entry.environment.con)[0][1] == "dirty"
    assert refused(entry, "refused", "slot_dirty") == []  # the base check refuses it before any setup step


@pytest.mark.parametrize(
    ("blob", "status"),
    [(None, "refused"), (b"[]", "refused"), (b'{"setup": "just install"}', "refused"), (Unavailable("x"), "unavailable")],
    ids=["missing", "not_object", "bad_value", "git"],
)
def test_a_profile_that_cannot_be_read_refuses_before_the_reset(entry: Entry, blob: bytes | Unavailable | None, status: str) -> None:
    entry.environment.profiles = FakeProfiles(blob=blob)
    events = refused(entry, status, "environment:profile")
    assert "empty .env/s1" not in events and rows(entry.environment.con) == []


def test_the_preflight_refuses_another_platform_unsafe_removal_and_missing_folders(entry: Entry, slot: FakeWorktree) -> None:
    env = entry.environment
    env.platform = "darwin"
    refused(entry, "refused", "environment:platform")
    env.platform, env.safe_removal = "linux", False
    refused(entry, "refused", "environment:remove_unsafe")
    env.safe_removal = True
    env.files.unmakeable.add(folders(slot.path).tools)
    refused(entry, "unavailable", "environment:files")
    env.files.unmakeable.clear()
    env.files.unemptiable.add(folders(slot.path).tmp)
    assert refused(entry, "unavailable", "environment:files")[-1] == "empty .t/s1"
    assert rows(env.con) == []


def test_an_uncleanable_uv_folder_refuses_before_any_command(entry: Entry, slot: FakeWorktree) -> None:
    entry.environment.files.unemptiable.add(folders(slot.path).env)
    events = refused(entry, "unavailable", "environment:files")
    assert events[-1] == "empty .env/s1" and rows(entry.environment.con) == []


def test_an_implement_attempt_without_its_environment_is_refused(entry: Entry) -> None:
    entry.wired = False
    assert refused(entry, "unavailable", "environment:unwired") == []


def test_a_plan_attempt_runs_no_setup_even_on_another_platform(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles, tmp_path: Path
) -> None:
    environment = Environment(registered, checkouts, tmp_path, platform="darwin")
    Entry(environment, checkouts, slot_files).execute()
    assert environment.events == ["agent"] and rows(registered) == []


def test_a_repeat_keeps_its_environment_and_only_empties_the_scratch(entry: Entry, slot: FakeWorktree, checkouts: Checkouts) -> None:
    """A repeat (attempt 2) runs steps 1-4 and 9-11: no profile read, no reset, no command."""
    env = entry.environment
    record = AttemptStore(lambda: env.con).load(KEY)
    assert record is not None
    repeat = dataclasses.replace(record, admission=dataclasses.replace(record.admission, number=2))
    gitdir = slot.repo.identity().common_dir / "worktrees" / "s1"
    assert env.preparation().prepare(repeat, Prepared("d" * 40, gitdir, slot.repo.path), held, {}) is None
    assert env.events == ["ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1", "empty .t/s1"]
    assert env.profiles.read == [] and rows(env.con) == []
