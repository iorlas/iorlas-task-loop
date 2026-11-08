"""WriteState: the write stage's own state is not a checkpointed field, and starts empty."""
import msgspec
from tlkernel.checkpoint import RunState

from tlwork.write.state import WriteState

OWNED = {"write_rounds", "last_summary", "account_notes", "strays"}


def test_the_checkpoint_record_holds_none_of_the_write_fields():
    assert not OWNED & {f.name for f in msgspec.structs.fields(RunState)}


def test_a_new_write_state_is_empty():
    w = WriteState()
    assert (w.write_rounds, w.last_summary, w.account_notes, w.strays) == ([], "", [], [])
