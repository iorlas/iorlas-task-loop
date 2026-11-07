"""Two writers of one bead's park never lose each other's change: the read, the rule and the write are one transaction."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import support.paths  # noqa: F401
from support.tmpdir import TemporaryDirectory

from taskloop.contracts.ids import BeadId
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir

BEAD = BeadId("tl-1")


def counted(old: Park | None) -> Park:
    return old.replace(runs=old.runs + 1) if old else Park(bead=BEAD, hash="h", runs=1, run="r", t=0.0)


@pytest.fixture
def store():
    with TemporaryDirectory() as tmp:
        yield ParkStore(ConfigDir(Path(tmp)))


def test_changes_from_two_threads_all_count(store):
    barrier = Barrier(2, timeout=30)

    def work(_: int) -> None:
        mine = ParkStore(store.cfg)
        barrier.wait()
        for _ in range(25):
            mine.change(BEAD, counted)

    with ThreadPoolExecutor(max_workers=2) as threads:
        list(threads.map(work, range(2)))
    got = store.get(BEAD)
    assert got is not None and got.runs == 50


def test_change_sees_the_stored_park_and_returns_the_new_one(store):
    assert store.change(BEAD, counted).runs == 1
    assert store.change(BEAD, counted).runs == 2
    assert store.get(BEAD).runs == 2  # type: ignore[union-attr]
