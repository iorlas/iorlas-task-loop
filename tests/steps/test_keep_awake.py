"""Keep-awake while `tl step rounds` runs (`keep_awake`, wired in `cli_composition.open_rounds`), through a semantic fake of
the spawn port and of the rounds' SIGINT handler: the helper's command per platform, best effort without a tool, and the
order spawn, replay, handler, rounds, handler restored, helper stopped on every way out. No handler is installed and no
process started here (the real spawn: `real/test_keep_awake_real.py`)."""

import ast
import os
import sys
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest
from install_doubles import A, make_install
from sqlite_store import Store

from taskloop import cli_composition
from taskloop.factory_schema import SCHEMA
from taskloop.installs import Manifest
from taskloop.interrupts import Interrupts
from taskloop.keep_awake import Helper, Host, Unavailable, command
from taskloop.round import NextRequest

TOOLS = {"caffeinate": "/usr/bin/caffeinate", "systemd-inhibit": "/bin/systemd-inhibit", "tail": "/bin/tail"}
LINUX = ["/bin/systemd-inhibit", "--what=sleep:idle", "--who=taskloop", "--why=tl step rounds tasks", "--mode=block",
         "/bin/tail", "--pid=4242", "-f", "/dev/null"]


class Machine:
    """A host whose spawn records the argv and returns a helper that records its replay and stop; `replayed` is raised
    by the replay (a Ctrl-C noted during the spawn), `refused` by the spawn. `install` is the rounds' handler, recorded."""

    def __init__(self, platform: str = "linux", tools: dict[str, str] | None = None, refused: OSError | None = None,
                 replayed: BaseException | None = None) -> None:
        self.events, self.argv, self.said = list[str](), list[list[str]](), list[str]()
        self.host = Host(platform, (TOOLS if tools is None else tools).get, self.spawn)
        self.refused, self.replayed = refused, replayed

    def spawn(self, argv: Sequence[str]) -> Helper:
        self.argv.append(list(argv))
        if self.refused is not None:
            raise self.refused
        self.events.append("spawn")
        return Helper(77, self.replay, lambda: self.events.append("stop"))

    def replay(self) -> None:
        self.events.append("replay")
        if self.replayed is not None:
            raise self.replayed

    @contextmanager
    def install(self, say: Callable[[str], object]) -> Generator[Interrupts]:
        self.events.append("install")
        try:
            yield Interrupts(say, lambda: None)
        finally:
            self.events.append("restore")


@pytest.mark.parametrize(("platform", "expected"), [
    ("darwin", ["/usr/bin/caffeinate", "-i", "-w", "4242"]),
    ("linux", LINUX),
    ("freebsd14", Unavailable("platform", "no keep-awake helper on freebsd14")),
    ("win32", Unavailable("platform", "no keep-awake helper on win32")),
])
def test_the_helper_command_by_platform_waits_for_the_rounds_pid(platform: str, expected: list[str] | Unavailable) -> None:
    assert command(Machine(platform).host, 4242, "tasks") == expected


@pytest.mark.parametrize(("platform", "present", "detail"), [
    ("darwin", {}, "caffeinate not on PATH"),
    ("linux", {"tail": "/bin/tail"}, "systemd-inhibit not on PATH"),
    ("linux", {"systemd-inhibit": "/bin/systemd-inhibit"}, "tail not on PATH"),
])
def test_a_missing_tool_is_unavailable(platform: str, present: dict[str, str], detail: str) -> None:
    assert command(Machine(platform, present).host, 1, "tasks") == Unavailable("missing", detail)


def request(tmp_path: Path) -> NextRequest:
    return NextRequest("tasks", str(tmp_path), tmp_path, "auto", "m", "high", 30)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    con.close()
    return path


def logged(tmp_path: Path) -> list[str]:
    path = tmp_path / "art" / "rounds.log"
    return [line.split(" ", 2)[2] for line in path.read_text().splitlines()] if path.exists() else []


def rounds(database: Path, machine: Machine, body: Callable[[Interrupts], None] = lambda _interrupts: None) -> None:
    """`open_rounds` with the machine; the body stands for the rounds and gets the handler's flag (press it for a
    graceful stop)."""
    with cli_composition.open_rounds(database, database.parent / "art", request(database.parent), machine.host,
                                     machine.install) as ports:
        assert not isinstance(ports, cli_composition.Failed)
        machine.events.append("rounds")
        flag = Interrupts(machine.said.append, lambda: None)
        body(flag)
        assert ports.pid == os.getpid()


def test_the_helper_starts_before_the_handler_replays_first_and_is_stopped_after_it(database: Path, tmp_path: Path) -> None:
    machine = Machine()
    rounds(database, machine)
    assert machine.events == ["spawn", "replay", "install", "rounds", "restore", "stop"]
    assert [argv[-3] for argv in machine.argv] == [f"--pid={os.getpid()}"]
    assert logged(tmp_path) == ["rounds keep_awake started pid=77"] and machine.said == []
    rounds(database, machine)  # the rounds lock was released: a second rounds starts a second helper
    assert machine.events.count("stop") == 2


def press_twice(interrupts: Interrupts) -> None:
    interrupts.press()  # the first Ctrl-C: graceful
    raise KeyboardInterrupt  # the second: abrupt


def fail(_interrupts: Interrupts) -> None:
    raise RuntimeError("a round raised")


@pytest.mark.parametrize("body", [press_twice, fail])
def test_the_helper_is_stopped_when_the_rounds_raise(body: Callable[[Interrupts], None], database: Path) -> None:
    machine = Machine()
    with pytest.raises((KeyboardInterrupt, RuntimeError)):
        rounds(database, machine, body)
    assert machine.events == ["spawn", "replay", "install", "rounds", "restore", "stop"]


def test_a_ctrl_c_during_the_spawn_is_replayed_before_the_handler_and_still_stops_the_helper(database: Path) -> None:
    machine = Machine(replayed=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        rounds(database, machine)
    assert machine.events == ["spawn", "replay", "stop"]
    rounds(database, Machine())  # the lock is released on this way out too


@pytest.mark.parametrize(("machine", "word", "said"), [
    (Machine("linux", {}), "unavailable:missing", "systemd-inhibit, tail not on PATH"),
    (Machine("sunos5"), "unavailable:platform", "no keep-awake helper on sunos5"),
    (Machine("darwin", refused=FileNotFoundError(2, "No such file")), "unavailable:start",
     "/usr/bin/caffeinate: FileNotFoundError: [Errno 2] No such file"),
])
def test_without_a_helper_the_rounds_run_anyway_after_one_line_each(
    machine: Machine, word: str, said: str, database: Path, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    rounds(database, machine)
    assert machine.events == ["install", "rounds", "restore"]
    assert logged(tmp_path) == [f"rounds keep_awake {word}"]
    assert capfd.readouterr().err == f"Keep-awake unavailable ({said}); the rounds run anyway\n"


@pytest.mark.parametrize("managed", [True, False])
def test_the_rounds_ports_carry_the_install_this_process_runs_from(
    database: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, managed: bool
) -> None:
    """`open_rounds` reads `installs.running` of `sys.prefix` under this home once: the `rounds install` line's install."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    install = make_install(home, A, "factory-v0.2.0")
    monkeypatch.setattr(sys, "prefix", str(install / "venv" if managed else tmp_path / "runner" / ".venv"))
    machine = Machine()
    with cli_composition.open_rounds(database, tmp_path / "art", request(tmp_path), machine.host, machine.install) as ports:
        assert not isinstance(ports, cli_composition.Failed)
        assert ports.install == (Manifest(A, "factory-v0.2.0", "2026-11-20T10:00:00Z", "/home/u/src/task-loop") if managed else None)


def test_refused_rounds_start_no_helper(tmp_path: Path) -> None:
    machine = Machine()
    with cli_composition.open_rounds(tmp_path / "absent.db", tmp_path / "art", request(tmp_path), machine.host,
                                     machine.install) as ports:
        assert isinstance(ports, cli_composition.Failed) and ports.reason == "database"
    assert machine.events == machine.argv == []


def test_only_the_rounds_opener_reaches_the_helper() -> None:
    """No other command starts one: `awake` and the real host are named in `open_rounds` only, and only the two
    composition modules import `keep_awake`."""
    source = Path(cli_composition.__file__)
    tree = ast.parse(source.read_text())
    users = {function.name for function in ast.walk(tree) if isinstance(function, ast.FunctionDef)
             for node in ast.walk(function) if isinstance(node, ast.Name) and node.id in {"awake", "keep_awake_host"}}
    assert users == {"open_rounds"}
    importers = {path.name for path in source.parent.glob("*.py") if "taskloop.keep_awake" in path.read_text()}
    assert importers == {"cli_composition.py", "composition.py"}
