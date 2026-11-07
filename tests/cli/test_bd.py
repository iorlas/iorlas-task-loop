"""Required bd failures retain their historical command exit code and diagnostic."""
import os
from pathlib import Path
from unittest import mock

import pytest
from support.tlmain import tl, tl_main

from taskloop.adapters import beadtools
from taskloop.cli import bd
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.bead import BdError
from tlkernel.beadsport import BdFailure
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class BdExit(Case):
    def test_required_adapter_failure_exits_with_the_same_message(self):
        call = mock.Mock(side_effect=BdFailure(BdError(kind="other", text="database locked")))
        with pytest.raises(SystemExit) as caught:
            bd.required(beadtools.must, call)
        assert caught.value.code == "tl: database locked"

    def test_required_success_passes_arguments_and_result(self):
        call = mock.Mock(return_value=7)
        assert bd.required(call, "bead", reason="done") == 7
        call.assert_called_once_with("bead", reason="done")

    def test_other_errors_propagate(self):
        with pytest.raises(ValueError):
            bd.required(mock.Mock(side_effect=ValueError("bad input")))

    def test_dispatch_reports_required_failure_as_exit_one_on_stderr(self):
        call = mock.Mock(side_effect=BdFailure(BdError(kind="other", text="database locked")))

        def verb(_args, _ctx):
            return beadtools.must(call)

        with mock.patch.object(tl, "Ctx"), mock.patch.dict(tl.VERBS, {"actor": verb}):
            result = tl_main("actor", cwd=Path.cwd())
        assert (result.returncode, result.stdout, result.stderr) == (1, "", "tl: database locked\n")

    def test_tl_runs_with_umask_077_so_its_files_are_the_owners_alone(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        with mock.patch.object(tl, "Ctx"), mock.patch.dict(tl.VERBS, {"actor": lambda _a, _c: 0}):
            tl_main("actor", cwd=Path.cwd())
        seen = os.umask(0o022)
        assert seen == 0o077

    def test_dispatch_reports_missing_bd_as_before(self):
        with mock.patch.object(tl, "Ctx"), mock.patch.object(beadtools.shutil, "which", return_value=None):
            result = tl_main("task", "ready", cwd=Path.cwd())
        assert (result.returncode, result.stdout, result.stderr) == (1, "", "tl: bd is not on PATH\n")

    def test_bd_is_an_unknown_verb_before_context_or_adapter_creation(self):
        with mock.patch.object(tl, "Ctx") as context, mock.patch.object(beadtools, "bd_store") as store:
            result = tl_main("bd", "show", "X", cwd=Path.cwd())
        assert result.returncode == 2
        assert "invalid choice: 'bd'" in result.stderr
        context.assert_not_called()
        store.assert_not_called()

    def test_task_show_reaches_the_guarded_adapter_passthrough(self):
        context = mock.Mock()
        context.who.config.root = Path(self.enterContext(TemporaryDirectory()))  # a config dir in the current layout
        context.who.actor = "tl-session"
        store = mock.Mock()
        store.passthrough.return_value = mock.Mock(out="shown\n", err="", code=0)
        with (mock.patch.object(tl, "Ctx", return_value=context), mock.patch.object(tl.ident, "layout_stop", return_value=""),
              mock.patch.object(beadtools, "bd_store", return_value=store) as factory,
              mock.patch.object(tl.cli_closing, "guard", return_value=mock.Mock()) as guard):
            result = tl_main("task", "show", "X", cwd=Path.cwd())
        assert (result.returncode, result.stdout, result.stderr) == (0, "shown\n", "")
        factory.assert_called_once_with("tl-session")
        guard.assert_called_once_with(context.who, context.git, store)
        store.passthrough.assert_called_once_with(["show", "X"])

    def test_task_close_refusal_stops_before_adapter_execution(self):
        context, store = mock.Mock(), mock.Mock()
        context.who.config.root = Path(self.enterContext(TemporaryDirectory()))
        refusal = mock.Mock(return_value="no land on record; use tl task close X --reason duplicate")
        with (mock.patch.object(tl, "Ctx", return_value=context), mock.patch.object(tl.ident, "layout_stop", return_value=""),
              mock.patch.object(beadtools, "bd_store", return_value=store),
              mock.patch.object(tl.cli_closing, "guard", return_value=refusal)):
            result = tl_main("task", "close", "X", cwd=Path.cwd())
        assert result.returncode == 1
        assert "no land on record" in result.stderr
        refusal.assert_called_once_with("X", "")
        store.passthrough.assert_not_called()

    def test_missing_bd_failure_exits_at_cli_boundary(self):
        call = mock.Mock(side_effect=BdCommandFailure("tl: bd is not on PATH"))
        with pytest.raises(SystemExit) as caught:
            bd.required(call)
        assert caught.value.code == "tl: bd is not on PATH"
