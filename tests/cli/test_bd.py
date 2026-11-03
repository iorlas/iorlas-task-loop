"""Required bd failures retain their historical command exit code and diagnostic."""
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401
from support.tlmain import tl, tl_main

from taskloop.adapters import beadtools
from taskloop.cli import bd
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.bead import BdError
from taskloop.contracts.ports import BdFailure


class BdExit(unittest.TestCase):
    def test_required_adapter_failure_exits_with_the_same_message(self):
        call = mock.Mock(side_effect=BdFailure(BdError(kind="other", text="database locked")))
        with self.assertRaises(SystemExit) as caught:
            bd.required(beadtools.must, call)
        self.assertEqual(caught.exception.code, "tl: database locked")

    def test_required_success_passes_arguments_and_result(self):
        call = mock.Mock(return_value=7)
        self.assertEqual(bd.required(call, "bead", reason="done"), 7)
        call.assert_called_once_with("bead", reason="done")

    def test_other_errors_propagate(self):
        with self.assertRaises(ValueError):
            bd.required(mock.Mock(side_effect=ValueError("bad input")))

    def test_dispatch_reports_required_failure_as_exit_one_on_stderr(self):
        call = mock.Mock(side_effect=BdFailure(BdError(kind="other", text="database locked")))

        def verb(_args, _ctx):
            return beadtools.must(call)

        with mock.patch.object(tl, "Ctx"), mock.patch.dict(tl.VERBS, {"actor": verb}):
            result = tl_main("actor", cwd=Path.cwd())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, "", "tl: database locked\n"))

    def test_dispatch_reports_missing_bd_as_before(self):
        with mock.patch.object(tl, "Ctx"), mock.patch.object(beadtools.shutil, "which", return_value=None):
            result = tl_main("bd", "ready", cwd=Path.cwd())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, "", "tl: bd is not on PATH\n"))

    def test_missing_bd_failure_exits_at_cli_boundary(self):
        call = mock.Mock(side_effect=BdCommandFailure("tl: bd is not on PATH"))
        with self.assertRaises(SystemExit) as caught:
            bd.required(call)
        self.assertEqual(caught.exception.code, "tl: bd is not on PATH")
