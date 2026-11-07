"""`FakeBeads`: bd in memory for the tests. It is the bd `tl selftest` runs on (app/doctor/memory_beads.py), named for its use here;
the Beads contract (tests/ports/beads_contract.py) holds it equal to real bd."""
from taskloop.app.doctor.memory_beads import MemoryBeads as FakeBeads

__all__ = ["FakeBeads"]
