"""Notes file the supplied follow-up capability once and checkpoint its counts."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from taskloop.adapters import beadtools
from tlkernel.enums import Outcome
from tlpipeline.api import FileNotes
from tlpipeline.testing import FakeFollowUps


@pytest.mark.parametrize('refused', [False, True])
def test_file_notes_calls_followups_once_and_keeps_counts(refused):
    leftover = {'title': 'later', 'why': 'needed'}
    host = SimpleNamespace(bead='t-1', leftovers=[leftover], filed=[], checkpoints=Mock(),
                           pictures=Mock(), warn=Mock())
    host.pictures.keep_evidence.return_value = []
    followups = FakeFollowUps([leftover] if refused else [])
    noted = FileNotes(host, followups, beadtools.attempt).run(Outcome.FAILED)
    assert followups.calls == [()]
    assert (noted.filed, noted.unfiled) == (0 if refused else 1, int(refused))
    host.checkpoints.keep_pending.assert_called_once_with()
    host.checkpoints.keep_notes.assert_called_once_with(noted)
    assert host.warn.called is refused
