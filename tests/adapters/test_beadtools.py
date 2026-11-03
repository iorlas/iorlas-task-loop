"""Shared tolerant bd helpers and typed failures of required adapter operations."""
import unittest
from unittest import mock

import support.paths  # noqa: F401

from taskloop.adapters import bdsafe, beadtools
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.bead import BdError, Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure


class BeadTools(unittest.TestCase):
    def test_tolerant_helpers_have_one_implementation(self):
        self.assertIs(beadtools.peek, bdsafe.peek)
        self.assertIs(beadtools.attempt, bdsafe.attempt)
        self.assertIs(beadtools.listed, bdsafe.listed)

    def test_tolerant_helpers_preserve_success(self):
        bead = Bead(id=BeadId("t-1"), title="Task", status="open")
        store = mock.Mock()
        store.show.return_value = bead
        store.ready.return_value = [bead]
        self.assertIs(bdsafe.peek(store, bead.id), bead)
        self.assertEqual(bdsafe.listed(store.ready, label="queue"), [bead])
        store.ready.assert_called_once_with(label="queue")
        self.assertTrue(bdsafe.attempt(store.close, bead.id, reason="done"))
        store.close.assert_called_once_with(bead.id, reason="done")

    def test_tolerant_helpers_swallow_only_bd_failures(self):
        store = mock.Mock()
        for error in (BdFailure(BdError(kind="other", text="locked")), ValueError("bad input")):
            store.show.side_effect = error
            call = mock.Mock(side_effect=error)
            if isinstance(error, BdFailure):
                self.assertIsNone(bdsafe.peek(store, BeadId("t-1")))
                self.assertEqual(bdsafe.listed(call), [])
                self.assertFalse(bdsafe.attempt(call))
            else:
                with self.assertRaises(ValueError):
                    bdsafe.peek(store, BeadId("t-1"))
                with self.assertRaises(ValueError):
                    bdsafe.listed(call)
                with self.assertRaises(ValueError):
                    bdsafe.attempt(call)

    def test_required_failure_raises_with_the_original_diagnostic(self):
        refusal = BdFailure(BdError(kind="other", text="database locked"))
        with self.assertRaises(BdCommandFailure) as caught:
            beadtools.must(mock.Mock(side_effect=refusal))
        self.assertEqual(str(caught.exception), "tl: database locked")
        self.assertIs(caught.exception.__cause__, refusal)

    def test_required_success_returns_the_result(self):
        call = mock.Mock(return_value=BeadId("t-1"))
        self.assertEqual(beadtools.must(call, "title", priority=0), BeadId("t-1"))
        call.assert_called_once_with("title", priority=0)

    def test_missing_executable_raises_instead_of_exiting(self):
        with mock.patch.object(beadtools.shutil, "which", return_value=None), self.assertRaises(BdCommandFailure) as caught:
            beadtools.bd_store("owner")
        self.assertEqual(str(caught.exception), "tl: bd is not on PATH")
