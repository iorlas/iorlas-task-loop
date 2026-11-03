"""Check spawn errors are saved as failed results, including when the executable vanished after plan validation."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.checks import ck
from support.engine_case import EngineTest

from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.cache import RunMemo
from taskloop.contracts.checks import Check
from taskloop.contracts.ids import CheckId


class SpawnFailure(EngineTest):
    def test_spawn_os_errors_become_failed_check_results_with_diagnostics(self):
        eng = self.checks_engine(base_red=False)
        for error, code in ((FileNotFoundError("executable vanished"), 127),
                            (PermissionError("permission denied"), 126), (OSError("exec format error"), 126)):
            with self.subTest(error=error):
                with mock.patch.object(eng, "sh", side_effect=error), mock.patch.object(eng.checker, "_diff_check", return_value=[]):
                    run = eng.run_checks({"checks": ck(["./missing/check"]), "files": []}, "spawn failure")
                failed = next(c for c in run.failed if c.cmd == "./missing/check")
                self.assertEqual((failed.status, failed.exit), ("failed", code))
                self.assertIn("could not start", failed.tail)
                self.assertIn(str(error), failed.tail)
                self.assertIn(str(error), (eng.run_dir / failed.log).read_text())

    def test_a_spawn_failure_on_the_base_also_returns_an_exit_code(self):
        eng = self.checks_engine()
        base = BaseCheck(eng, mock.Mock(spec=RunMemo), enabled=False)
        for error, code in ((FileNotFoundError("missing"), 127), (OSError("bad executable"), 126)):
            with self.subTest(error=error), mock.patch.object(eng, "sh", side_effect=error):
                self.assertEqual(base._rc(self.wt, Check(id=CheckId("spawn"), cmd="./missing/check"), None), code)
