"""Checks: the shared contract on the fake and on ShellChecks (driven by a python interpreter, never bash or just), and
logic tests on the fake."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import support.paths  # noqa: E402,F401
from support.tags import contract, domain  # noqa: E402
from taskloop.adapters.checks_shell import ShellChecks  # noqa: E402
from taskloop.adapters.fake_checks import FakeChecks, failed, hung, passed  # noqa: E402
from taskloop.contracts.ports import Checks, CheckSpec  # noqa: E402


class ChecksContract:
    """A subclass gives `make()` and four commands: PASS prints "fine", FAIL prints "boom" and exits 3, HANG never ends,
    ENV prints $PROBE."""

    PASS = FAIL = HANG = ENV = ""

    def make(self) -> Checks:
        raise NotImplementedError

    def go(self, cmd: str, **kw: object) -> object:
        return self.make().run(CheckSpec(cmd=cmd, cwd=tempfile.gettempdir(), **kw))  # type: ignore[arg-type]

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
    PASS, FAIL, HANG, ENV = "pass", "fail", "hang", "env"

    def make(self) -> FakeChecks:
        return FakeChecks().when("pass", passed("fine")).when("fail", failed("boom", 3)).when("hang", hung())

    def test_the_environment_reaches_the_command(self) -> None:
        f = self.make()
        f.run(CheckSpec(cmd="env", cwd=".", env={"PROBE": "seen"}))
        self.assertEqual(f.ran[0].env, {"PROBE": "seen"})


@contract
class ShellChecksContract(ChecksContract, unittest.TestCase):
    PASS = "print('fine')"
    FAIL = "import sys; print('boom'); sys.exit(3)"
    HANG = "import time; time.sleep(60)"
    ENV = "import os; print(os.environ['PROBE'])"

    def make(self) -> ShellChecks:
        return ShellChecks(shell=[sys.executable, "-c"])


@domain
class FakeChecksLogic(unittest.TestCase):
    def test_unscripted_commands_pass_and_are_recorded(self) -> None:
        f = FakeChecks()
        self.assertTrue(f.run(CheckSpec(cmd="just check", cwd="/w")).passed)
        self.assertEqual([(s.cmd, s.cwd) for s in f.ran], [("just check", "/w")])

    def test_red_then_green_then_green_forever(self) -> None:
        f = FakeChecks().when("t", failed("x"), passed())
        spec = CheckSpec(cmd="t", cwd=".")
        self.assertEqual([f.run(spec).passed for _ in range(3)], [False, True, True])

    def test_a_default_can_be_red(self) -> None:
        self.assertFalse(FakeChecks(default=failed()).run(CheckSpec(cmd="anything", cwd=".")).passed)


if __name__ == "__main__":
    unittest.main()
