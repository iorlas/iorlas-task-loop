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
from doubles import CHECKS, Command, Environment, FakeProfiles
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree

from taskloop.access import folders
from taskloop.agents.launch import AgentLaunch, codex_access
from taskloop.agents.settings import AgentSetting, ClaudePolicy, CodexPolicy, OpenCodePolicy, encode_policy
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, AttemptResult, Checkouts, SlotFiles
from taskloop.environment import Renewal, SetupFor, setup_digest
from taskloop.evidence_files import EvidenceFiles
from taskloop.harness_choice import HarnessKind
from taskloop.prepare import Prepared
from taskloop.profile import Unavailable

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
UNCHANGED = {"disposition": "unchanged", "paths": [], "message": None, "explanation": "nothing to do"}
ROW = "SELECT run,conclusion,rc,command,pid FROM setup_run ORDER BY run"


@pytest.fixture
def root(request: pytest.FixtureRequest) -> Path:
    """The slots root, short as a person's would be (the TMPDIR budget is the real one here), or the test's own
    (`indirect`); the Git fake and the environment fakes never touch it."""
    return getattr(request, "param", Path("/s"))


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
    specs: list[LaunchSpec] = dataclasses.field(default_factory=list)

    def agent(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.environment.events.append("agent")
        self.specs.append(spec)
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(UNCHANGED), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    def renew(self) -> Renewal:
        self.environment.events.append("renew")
        return self.renewals.pop(0) if self.renewals else "held"

    def execute(self) -> AttemptResult:
        env = self.environment
        attempts = Attempts(
            AttemptStore(lambda: env.con),
            EvidenceFiles(env.artifacts),
            AgentLaunch(lambda _harness: ("/bin/codex", {"HOME": "/home/p"})),
            self.agent,
            env.clock,
            self.checkouts,
            self.files,
            environment=env.preparation() if self.wired else None,
        )
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
        "ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1", "probe",
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
        "ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1", "probe", "empty .t/s1", "renew", "agent"]
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
    assert (
        env.preparation().prepare(
            repeat,
            Prepared("d" * 40, gitdir, slot.repo.path),
            held,
            ("/bin/codex", {}),
            codex_access(CodexPolicy(), folders(slot.path)).sandbox_argv("/bin/codex", ["true"]),
        )
        is None
    )
    assert env.events == ["ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools", "empty .t/s1", "probe", "empty .t/s1"]
    assert env.profiles.read == [] and rows(env.con) == []


@pytest.mark.parametrize(
    ("command", "conclusion"), [(Command(lingering=True), "lingering"), (Command(timed_out=True, rc=None), "timed_out")]
)
def test_a_process_left_by_a_concluded_run_holds_every_later_step_until_its_group_is_gone(
    entry: Entry, command: Command, conclusion: str
) -> None:
    """Concluded, but its last command's group may still hold a process: no reset, setup or dispatch while it lives."""
    env = entry.environment
    env.process.script = [command]
    entry.execute()
    env.seen[501] = "alive"
    assert refused(entry, "unavailable", "environment:running") == ["seen 501"]
    env.seen[501] = "unknown"
    assert refused(entry, "unavailable", "environment:unknown") == ["seen 501"]
    env.seen[501] = "gone"
    entry.execute()
    assert [row[:2] for row in rows(env.con)] == [(1, conclusion), (2, "passed")]
    assert env.events[-1] == "agent"


def test_a_slot_moved_by_setup_is_a_failed_run(entry: Entry, slot: FakeWorktree) -> None:
    """Setup checked out another branch (or committed): the agent would start elsewhere than B on `task/<id>`."""
    entry.environment.process.script = [Command(effect=lambda: slot.checkout_new("elsewhere"))]
    refused(entry, "refused", "environment:moved")
    assert rows(entry.environment.con)[0][1] == "dirty"


@pytest.mark.parametrize(("lingering", "conclusion", "reason"), [(False, "failed", "environment:exit"),
                                                                    (True, "lingering", "environment:lingering")])
def test_a_supervision_failure_after_the_start_is_judged_by_its_group(entry: Entry, lingering: bool, conclusion: str, reason: str) -> None:
    """The command ran: its group is checked, never assumed empty."""
    entry.environment.process.script = [Command(supervision_error=True, lingering=lingering)]
    events = refused(entry, "unavailable", reason)
    assert "group 501" in events and rows(entry.environment.con) == [(1, conclusion, None, 0, 501)]
    log = EvidenceFiles(entry.environment.artifacts).setup_log(KEY, 1).read_text()
    assert log == "$ just bootstrap\ndone\nended uncertainly\n" + ("lingering\n" if lingering else "")


ENSURED = ["ensure .t/s1", "ensure s1/uv-cache", "ensure s1/uv-tools"]


def test_the_implement_agent_writes_its_folders_offline_and_the_probe_sees_what_it_will(entry: Entry, slot: FakeWorktree) -> None:
    """The agent's access names exactly the three folders and gives only its shell TMPDIR, uv's folders and uv offline;
    Codex's own environment stays the scrubbed credentials' (its temporary files stay out of the roots). The probe ran
    `codex` with that environment and those folders. Setup had network."""
    entry.execute()
    found, env = folders(slot.path), entry.environment
    (spec,) = entry.specs
    access = codex_access(CodexPolicy(), found).config()
    flags = spec.argv.index("--json")
    assert spec.argv[flags - len(access) : flags] == list(access) and spec.env == {"HOME": "/home/p"}
    shell = {
        key.removeprefix("shell_environment_policy.set."): json.loads(value)
        for key, _, value in (item.partition("=") for item in access)
        if key.startswith("shell_environment_policy.set.")
    }
    assert shell == {"TMPDIR": str(found.tmp), "UV_CACHE_DIR": str(found.cache), "UV_TOOL_DIR": str(found.tools), "UV_OFFLINE": "1"}
    (probe,) = env.probes
    assert list(probe.exe[:2]) == ["/bin/codex", "sandbox"]
    assert probe.exe[4:4 + len(access)] == tuple(access)
    assert (probe.env, probe.folders) == ({"HOME": "/home/p"}, found)
    assert "UV_OFFLINE" not in env.process.calls[0].env


def test_a_plan_attempt_launches_with_plans_access_and_no_added_environment(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles, tmp_path: Path
) -> None:
    plan = Entry(Environment(registered, checkouts, tmp_path), checkouts, slot_files)
    plan.execute()
    (spec,) = plan.specs
    flags = spec.argv.index("--json")
    assert spec.argv[flags - len(codex_access(CodexPolicy()).flags() + codex_access(CodexPolicy()).config()) : flags] == list(
        codex_access(CodexPolicy()).flags() + codex_access(CodexPolicy()).config()
    ) and spec.env == {"HOME": "/home/p"}
    assert plan.environment.probes == []


@pytest.mark.parametrize(("root", "reason"), [(Path("/" + "r" * 52), None), (Path("/" + "r" * 53), "environment:path_long")],
                         ids=["64_bytes", "65_bytes"], indirect=["root"])
def test_a_tmpdir_over_64_bytes_is_refused_before_any_folder_is_made(entry: Entry, slot: FakeWorktree, reason: str | None) -> None:
    """A Unix socket path holds 107 bytes on Linux: 64 for TMPDIR leaves 43 for what a test appends."""
    assert len(str(folders(slot.path).tmp).encode()) == (64 if reason is None else 65)
    if reason is None:
        entry.execute()
        assert entry.environment.events[-1] == "agent"
    else:
        assert refused(entry, "refused", reason) == []


@pytest.mark.parametrize("case", ["into_slot", "evidence_holds_one", "outside_slots", "into_each_other", "slots_in_db_folder",
                                  "unreadable", "sibling_slot", "locks"])
def test_a_root_that_overlaps_what_the_agent_must_not_write_is_refused(entry: Entry, slot: FakeWorktree, case: str) -> None:
    """Resolved, links followed: each root must be exactly where it belongs beside the slot (never another slot, `.locks/`
    or another root), and none may equal, hold or sit inside the slot, its Git directories, the person's checkout, the
    evidence root or factory.db's folder."""
    env, base = entry.environment, slot.path.parent
    env.protected = (env.artifacts, Path("/db"))
    links = {
        "into_slot": {base / ".t": slot.path},
        "outside_slots": {base / ".t": Path("/elsewhere")},
        "into_each_other": {base / ".t": base / ".env"},  # .t/s1 is .env/s1, which holds both uv folders
        "sibling_slot": {base / ".t": base / "s2"},  # .t/s1 is s2/s1: inside another slot
        "locks": {base / ".env": base / ".locks"},  # the uv folders among the custody lock files
    }
    env.files.links = links.get(case, {})
    if case == "evidence_holds_one":  # an artifacts root set to `.t` beside the slots
        env.protected = (base / ".t", Path("/db"))
    if case == "slots_in_db_folder":
        env.protected = (env.artifacts, Path("/"))
    if case == "unreadable":
        env.files.unresolvable.add(folders(slot.path).tools)
    assert refused(entry, "refused", "environment:roots") == []


def test_a_sandbox_that_does_not_work_refuses_after_the_folders_are_made_and_runs_nothing(entry: Entry) -> None:
    entry.environment.sandbox = False
    assert refused(entry, "refused", "environment:sandbox") == [*ENSURED, "empty .t/s1", "probe"]
    assert rows(entry.environment.con) == []


@dataclasses.dataclass
class ChecksSlot:
    """A checks attempt's setup (`prepare_for` with X, detached, no probe) over the `checking` fixture's attempt and the
    Git fake's slot, detached at its HEAD, which stands for X."""

    environment: Environment
    slot: FakeWorktree

    @property
    def x(self) -> str:
        found = next(info.head for info in self.slot.repo.worktrees() if info.path == self.slot.path)
        assert found is not None
        return found

    def prepare(self, renewal: Renewal = "held") -> AttemptResult | None:
        env, gitdir = self.environment, self.slot.repo.identity().common_dir / "worktrees" / self.slot.path.name
        env.events.clear()
        target = SetupFor(CHECKS, self.slot.path, self.x, None, 100.0, True)
        return env.preparation().prepare_for(target, Prepared(self.x, gitdir, self.slot.repo.path), lambda: renewal,
                                             {"HOME": "/home/p"}, probe=None)


@pytest.fixture
def checks_slot(checking: sqlite3.Connection, checkouts: Checkouts, slot: FakeWorktree, tmp_path: Path) -> ChecksSlot:
    return ChecksSlot(Environment(checking, checkouts, tmp_path), slot)


def test_a_checks_slot_is_reset_hard_to_x_without_a_probe_then_set_up_at_x(checks_slot: ChecksSlot, slot: FakeWorktree) -> None:
    """A tracked file a killed check rewrote, and what it left untracked or ignored, are gone before setup runs."""
    slot.repo.exclude_locally([".venv/"])
    slot.write_file("README", "rewritten by a check")
    slot.write_file("left", "untracked")
    slot.write_file(".venv/planted", "ignored")
    seen: list[object] = []
    env = checks_slot.environment
    left = ("README", "left", ".venv/planted")
    env.process.script = [Command(effect=lambda: seen.append(tuple(slot.read_file(path) for path in left)))]
    assert checks_slot.prepare() is None
    assert seen == [("one", None, None)] and env.probes == []
    assert env.events == [*ENSURED, "empty .t/s1", "empty .env/s1", "ensure s1/uv-cache", "ensure s1/uv-tools",
                          "exec just bootstrap", "group 501", "empty .t/s1"]
    assert env.profiles.read == [checks_slot.x] and "UV_OFFLINE" not in env.process.calls[0].env
    stored = env.con.execute("SELECT attempt_id,run,commit_sha,conclusion FROM setup_run").fetchall()
    assert stored == [("checks", 1, checks_slot.x, "passed")]


def test_a_checks_slot_never_reuses_a_passed_setup(checks_slot: ChecksSlot) -> None:
    """Every block runs setup again: the one before ran task code on the host."""
    assert checks_slot.prepare() is None
    assert checks_slot.prepare() is None
    assert "exec just bootstrap" in checks_slot.environment.events
    assert [row[:2] for row in checks_slot.environment.con.execute(ROW).fetchall()] == [(1, "passed"), (2, "passed")]


def test_an_implement_slot_is_never_reset_hard(entry: Entry, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeWorktree, "reset", lambda *_args, **_options: pytest.fail("an implement slot holds its task branch"))
    entry.execute()
    assert entry.environment.events[-1] == "agent"


def test_a_checks_setup_must_leave_the_slot_detached_at_x(checks_slot: ChecksSlot, slot: FakeWorktree) -> None:
    checks_slot.environment.process.script = [Command(effect=lambda: slot.checkout_new("elsewhere"))]
    assert checks_slot.prepare() == AttemptResult("refused", "environment:moved")


@pytest.mark.parametrize("attached", [True, False], ids=["branch", "elsewhere"])
def test_a_checks_slot_not_detached_at_x_is_never_reset(checks_slot: ChecksSlot, slot: FakeWorktree, attached: bool) -> None:
    """A straggler checked out a branch (or another commit) after the take of X: the hard reset would carry that branch
    to X, so nothing is reset, cleaned or run."""
    x = checks_slot.x
    slot.write_file("README", "the straggler's")
    made = slot.record("a straggler's commit", paths="all")
    assert isinstance(made, Recorded)
    if attached:
        slot.checkout_new("straggler")
    slot.repo.exclude_locally([".venv/"])
    slot.write_file(".venv/kept", "x")
    env = checks_slot.environment
    target = SetupFor(CHECKS, slot.path, x, None, 100.0, True)
    gitdir = slot.repo.identity().common_dir / "worktrees" / slot.path.name
    found = env.preparation().prepare_for(target, Prepared(x, gitdir, slot.repo.path), held, {}, probe=None)
    assert found == AttemptResult("refused", "environment:moved")
    assert slot.read_file("README") == "the straggler's" and slot.read_file(".venv/kept") == "x"
    assert dict(slot.repo.branches("straggler")) == ({"straggler": made.sha} if attached else {})
    assert not any(event.startswith("exec") for event in env.events) and rows(env.con) == []


def test_failed_checks_setups_count_across_blocks_and_stop_after_two(checks_slot: ChecksSlot) -> None:
    env = checks_slot.environment
    env.process.script = [Command(rc=1), Command(rc=None, timed_out=True, survivors=True)]
    assert checks_slot.prepare() == AttemptResult("unavailable", "environment:exit")
    assert checks_slot.prepare() == AttemptResult("unavailable", "environment:lingering")  # survivors of the stop
    assert checks_slot.prepare() == AttemptResult("refused", "environment:failed")
    assert env.events == []  # counted before anything is observed, made or run
    assert [row[:2] for row in env.con.execute(ROW).fetchall()] == [(1, "failed"), (2, "lingering")]


def test_a_checks_setup_ends_with_the_claim_renewal_and_the_deadline(checks_slot: ChecksSlot) -> None:
    assert checks_slot.prepare("lost") == AttemptResult("refused", "claim_lost")
    checks_slot.environment.clock = lambda: 100
    assert checks_slot.prepare() == AttemptResult("refused", "expired")


def test_a_setup_stop_that_left_survivors_is_lingering_for_an_implement_slot_too(entry: Entry) -> None:
    entry.environment.process.script = [Command(rc=None, timed_out=True, survivors=True)]
    refused(entry, "unavailable", "environment:lingering")
    assert rows(entry.environment.con) == [(1, "lingering", None, 0, 501)]


@pytest.mark.parametrize("harness", [HarnessKind.CLAUDE, HarnessKind.OPENCODE])
def test_non_codex_implement_keeps_shared_setup_without_a_codex_probe(entry: Entry, harness: HarnessKind, tmp_path: Path) -> None:
    policy = (ClaudePolicy(settings_file=tmp_path / "captured.json", settings="{}")
              if harness is HarnessKind.CLAUDE else OpenCodePolicy())
    chosen = AgentSetting(harness=harness, model="chosen", effort="medium", access=policy)
    entry.environment.con.execute("UPDATE attempt SET harness=?,provider=?,model=?,effort=?,access_policy=?",
                                  (chosen.harness, chosen.provider, chosen.model, chosen.effort, encode_policy(policy)))
    result = entry.execute()
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert entry.environment.probes == [] and entry.environment.process.calls
    assert entry.environment.events[-3:] == ["empty .t/s1", "renew", "agent"]
