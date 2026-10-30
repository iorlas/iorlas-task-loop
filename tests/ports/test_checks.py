"""Checks: the shared contract on the fake and on ArgvChecks (exec'd as an argv, no shell), and logic tests on the fake."""
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_checks import FakeChecks, failed, hung, passed
from support.procsim import real_proc
from support.tags import contract, domain

from taskloop.adapters.checks_argv import ArgvChecks
from taskloop.contracts.ports import Checks, CheckSpec


class ChecksContract:
    """A subclass gives `make()` and four commands: PASS prints "fine", FAIL prints "boom" and exits 3, HANG never ends,
    ENV prints $PROBE."""

    PASS: ClassVar[list[str]] = []
    FAIL: ClassVar[list[str]] = []
    HANG: ClassVar[list[str]] = []
    ENV: ClassVar[list[str]] = []

    def make(self) -> Checks:
        raise NotImplementedError

    def go(self, argv: list[str], **kw: object) -> object:
        return self.make().run(CheckSpec(argv=argv, cwd=tempfile.gettempdir(), **kw))  # type: ignore[arg-type]

    def test_a_green_command_passes_with_its_output(self) -> None:
        r = self.go(self.PASS)
        self.assertEqual((r.exit, r.passed, "fine" in r.out), (0, True, True))  # type: ignore[attr-defined]

    def test_a_red_command_keeps_its_exit_and_output(self) -> None:
        r = self.go(self.FAIL)
        self.assertEqual((r.exit, r.passed, "boom" in r.out), (3, False, True))  # type: ignore[attr-defined]

    def test_a_command_past_its_deadline_is_a_timeout(self) -> None:
        r = self.go(self.HANG, timeout_s=0.5)
        self.assertEqual((r.exit, r.timed_out, r.passed), (124, True, False))  # type: ignore[attr-defined]

    def test_the_environment_reaches_the_command(self) -> None:
        r = self.go(self.ENV, env={"PROBE": "seen"})
        self.assertIn("seen", r.out)  # type: ignore[attr-defined]


@contract
class FakeChecksContract(ChecksContract, unittest.TestCase):
    PASS, FAIL, HANG, ENV = ["pass"], ["fail"], ["hang"], ["env"]

    def make(self) -> FakeChecks:
        return FakeChecks().when("pass", passed("fine")).when("fail", failed("boom", 3)).when("hang", hung())

    def test_the_environment_reaches_the_command(self) -> None:
        f = self.make()
        f.run(CheckSpec(argv=["env"], cwd=".", env={"PROBE": "seen"}))
        self.assertEqual(f.ran[0].env, {"PROBE": "seen"})


@contract
@real_proc("the ArgvChecks adapter is the real process: exit codes, output, the environment, no shell, the wall kill")
class ArgvChecksContract(ChecksContract, unittest.TestCase):
    PASS: ClassVar[Any] = ["echo", "fine"]  # no interpreter: the adapter's subject is a process, not Python
    FAIL: ClassVar[Any] = ["sh", "-c", "echo boom; exit 3"]
    HANG: ClassVar[Any] = ["sleep", "60"]
    ENV: ClassVar[Any] = ["sh", "-c", 'echo "$PROBE"']

    def make(self) -> ArgvChecks:
        return ArgvChecks()

    def test_no_shell_stands_between_the_argv_and_the_program(self) -> None:
        r = self.go(["echo", "$HOME && x"])
        self.assertIn("$HOME && x", r.out)  # type: ignore[attr-defined]


@domain
class FakeChecksLogic(unittest.TestCase):
    def test_unscripted_commands_pass_and_are_recorded(self) -> None:
        f = FakeChecks()
        self.assertTrue(f.run(CheckSpec(argv=["just", "check"], cwd="/w")).passed)
        self.assertEqual([(s.cmd, s.cwd) for s in f.ran], [("just check", "/w")])

    def test_red_then_green_then_green_forever(self) -> None:
        f = FakeChecks().when("t", failed("x"), passed())
        spec = CheckSpec(argv=["t"], cwd=".")
        self.assertEqual([f.run(spec).passed for _ in range(3)], [False, True, True])

    def test_a_default_can_be_red(self) -> None:
        self.assertFalse(FakeChecks(default=failed()).run(CheckSpec(argv=["anything"], cwd=".")).passed)


if __name__ == "__main__":
    unittest.main()
