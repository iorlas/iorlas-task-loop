"""Checks: the shared contract on the fake and on ArgvChecks (exec'd as an argv, no shell), and logic tests on the fake."""
import sys
from pathlib import Path
from typing import Any, ClassVar

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.argv_checks import ArgvChecks
from support.fake_checks import FakeChecks, failed, hung, passed
from support.tags import contract, domain

from tlkernel.checksport import Checks, CheckSpec
from tlkernel.env import snapshot
from tltestkit.procsim import real_proc


class ChecksContract:
    """A subclass gives `make()` and four commands: PASS prints "fine", FAIL prints "boom" and exits 3, HANG never ends,
    ENV prints $PROBE."""

    __test__ = False  # a mixin: only the subclasses below are collected

    PASS: ClassVar[list[str]] = []
    FAIL: ClassVar[list[str]] = []
    HANG: ClassVar[list[str]] = []
    ENV: ClassVar[list[str]] = []

    def make(self) -> Checks:
        raise NotImplementedError

    def go(self, argv: list[str], **kw: object) -> object:
        return self.make().run(CheckSpec(argv=argv, cwd=str(Path(__file__).parent), **kw))  # type: ignore[arg-type]

    def test_a_green_command_passes_with_its_output(self) -> None:
        r = self.go(self.PASS)
        assert (r.exit, r.passed, "fine" in r.out) == (0, True, True)  # type: ignore[attr-defined]

    def test_a_red_command_keeps_its_exit_and_output(self) -> None:
        r = self.go(self.FAIL)
        assert (r.exit, r.passed, "boom" in r.out) == (3, False, True)  # type: ignore[attr-defined]

    def test_a_command_past_its_deadline_is_a_timeout(self) -> None:
        r = self.go(self.HANG, timeout_s=0.5)
        assert (r.exit, r.timed_out, r.passed) == (124, True, False)  # type: ignore[attr-defined]

    def test_the_environment_reaches_the_command(self) -> None:
        r = self.go(self.ENV, env={"PROBE": "seen"})
        assert "seen" in r.out  # type: ignore[attr-defined]


@contract
class FakeChecksContract(ChecksContract, Case):
    __test__ = True
    PASS, FAIL, HANG, ENV = ["pass"], ["fail"], ["hang"], ["env"]

    def make(self) -> FakeChecks:
        return FakeChecks().when("pass", passed("fine")).when("fail", failed("boom", 3)).when("hang", hung())

    def test_the_environment_reaches_the_command(self) -> None:
        f = self.make()
        f.run(CheckSpec(argv=["env"], cwd=".", env={"PROBE": "seen"}))
        assert f.ran[0].env == {"PROBE": "seen"}


@contract
@real_proc("the ArgvChecks adapter is the real process: exit codes, output, the environment, no shell, the wall kill")
class ArgvChecksContract(ChecksContract, Case):
    __test__ = True
    PASS: ClassVar[Any] = ["echo", "fine"]  # no interpreter: the adapter's subject is a process, not Python
    FAIL: ClassVar[Any] = ["sh", "-c", "echo boom; exit 3"]
    HANG: ClassVar[Any] = ["sleep", "60"]
    ENV: ClassVar[Any] = ["sh", "-c", 'echo "$PROBE"']

    def make(self) -> ArgvChecks:
        return ArgvChecks(snapshot())

    def test_no_shell_stands_between_the_argv_and_the_program(self) -> None:
        r = self.go(["echo", "$HOME && x"])
        assert "$HOME && x" in r.out  # type: ignore[attr-defined]


@domain
class FakeChecksLogic(Case):
    def test_unscripted_commands_pass_and_are_recorded(self) -> None:
        f = FakeChecks()
        assert f.run(CheckSpec(argv=["just", "check"], cwd="/w")).passed
        assert [(s.cmd, s.cwd) for s in f.ran] == [("just check", "/w")]

    def test_red_then_green_then_green_forever(self) -> None:
        f = FakeChecks().when("t", failed("x"), passed())
        spec = CheckSpec(argv=["t"], cwd=".")
        assert [f.run(spec).passed for _ in range(3)] == [False, True, True]

    def test_a_default_can_be_red(self) -> None:
        assert not FakeChecks(default=failed()).run(CheckSpec(argv=["anything"], cwd=".")).passed
