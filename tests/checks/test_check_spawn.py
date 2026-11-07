"""Check spawn errors are saved as failed results, including when the executable vanished after plan validation."""
from unittest import mock

from support.check_host import CheckHostCase

from tlgate.base import BaseCheck
from tlgate.cache import RunMemo
from tlkernel.checks import Check
from tlkernel.ids import CheckId
from tltestkit.checks import ck


class SpawnFailure(CheckHostCase):
    def test_spawn_os_errors_become_failed_check_results_with_diagnostics(self):
        eng = self.checks_engine(base_red=False)
        for error, code in ((FileNotFoundError("executable vanished"), 127),
                            (PermissionError("permission denied"), 126), (OSError("exec format error"), 126)):
            with self.subTest(error=error):
                with mock.patch.object(eng, "sh", side_effect=error), mock.patch.object(eng.checker, "_diff_check", return_value=[]):
                    run = eng.run_checks({"checks": ck(["./missing/check"]), "files": []}, "spawn failure")
                failed = next(c for c in run.failed if c.cmd == "./missing/check")
                assert (failed.status, failed.exit) == ("failed", code)
                assert "could not start" in failed.tail
                assert str(error) in failed.tail
                assert str(error) in (eng.run_dir / failed.log).read_text()

    def test_a_spawn_failure_on_the_base_also_returns_an_exit_code(self):
        eng = self.checks_engine()
        base = BaseCheck(eng, mock.Mock(spec=RunMemo), enabled=False)
        for error, code in ((FileNotFoundError("missing"), 127), (OSError("bad executable"), 126)):
            with self.subTest(error=error), mock.patch.object(eng, "sh", side_effect=error):
                assert base._rc(self.wt, Check(id=CheckId("spawn"), cmd="./missing/check"), None) == code
