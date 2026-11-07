"""WriteState: the write stage's own state is not a checkpointed field, and starts empty."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import msgspec

from taskloop.app.write.state import WriteState
from tlkernel.checkpoint import RunState

OWNED = {"write_rounds", "last_summary", "lane_notes", "strays"}


def test_the_checkpoint_record_holds_none_of_the_write_fields():
    assert not OWNED & {f.name for f in msgspec.structs.fields(RunState)}


def test_a_new_write_state_is_empty():
    w = WriteState()
    assert (w.write_rounds, w.last_summary, w.lane_notes, w.strays) == ([], "", [], [])
