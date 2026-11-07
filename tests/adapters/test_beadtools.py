"""Shared tolerant bd helpers and typed failures of required adapter operations."""
from unittest import mock

import pytest

from taskloop.adapters import beadtools
from tlkernel import bdsafe
from tlkernel.bd_errors import BdCommandFailure
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId
from tltestkit.case import Case


class BeadTools(Case):
    def test_tolerant_helpers_have_one_implementation(self):
        assert beadtools.peek is bdsafe.peek
        assert beadtools.attempt is bdsafe.attempt
        assert beadtools.listed is bdsafe.listed

    def test_tolerant_helpers_preserve_success(self):
        bead = Bead(id=BeadId("t-1"), title="Task", status="open")
        store = mock.Mock()
        store.show.return_value = bead
        store.ready.return_value = [bead]
        assert bdsafe.peek(store, bead.id) is bead
        assert bdsafe.listed(store.ready, label="queue") == [bead]
        store.ready.assert_called_once_with(label="queue")
        assert bdsafe.attempt(store.close, bead.id, reason="done")
        store.close.assert_called_once_with(bead.id, reason="done")

    def test_tolerant_helpers_swallow_only_bd_failures(self):
        store = mock.Mock()
        for error in (BdFailure(BdError(kind="other", text="locked")), ValueError("bad input")):
            store.show.side_effect = error
            call = mock.Mock(side_effect=error)
            if isinstance(error, BdFailure):
                assert bdsafe.peek(store, BeadId("t-1")) is None
                assert bdsafe.listed(call) == []
                assert not bdsafe.attempt(call)
            else:
                with pytest.raises(ValueError):
                    bdsafe.peek(store, BeadId("t-1"))
                with pytest.raises(ValueError):
                    bdsafe.listed(call)
                with pytest.raises(ValueError):
                    bdsafe.attempt(call)

    def test_required_failure_raises_with_the_original_diagnostic(self):
        refusal = BdFailure(BdError(kind="other", text="database locked"))
        with pytest.raises(BdCommandFailure) as caught:
            beadtools.must(mock.Mock(side_effect=refusal))
        assert str(caught.value) == "tl: database locked"
        assert caught.value.__cause__ is refusal

    def test_required_success_returns_the_result(self):
        call = mock.Mock(return_value=BeadId("t-1"))
        assert beadtools.must(call, "title", priority=0) == BeadId("t-1")
        call.assert_called_once_with("title", priority=0)

    def test_missing_executable_raises_instead_of_exiting(self):
        with mock.patch.object(beadtools.shutil, "which", return_value=None), pytest.raises(BdCommandFailure) as caught:
            beadtools.bd_store("owner")
        assert str(caught.value) == "tl: bd is not on PATH"
