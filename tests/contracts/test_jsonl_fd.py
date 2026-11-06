"""A store that appended gives its descriptor back when it is dropped: a process that makes a store per test (or per run) must not run out
of descriptors (select() fails above 1024, then git cannot start: tests/slots/real failed at 1-2 xdist workers)."""
import gc
import os
from pathlib import Path

from taskloop.contracts.rotating import RotatingJsonl


def lowest_free_fd() -> int:
    """The number the next open() gets: it rises with every descriptor held below it."""
    fd = os.open(os.devnull, os.O_RDONLY)
    os.close(fd)
    return fd


def test_a_dropped_store_closes_the_file_it_appended_to(workdir):
    before = lowest_free_fd()
    stores = [RotatingJsonl(Path(workdir, f"s{i}.jsonl")) for i in range(20)]
    for store in stores:
        store.append({"a": 1})
    assert lowest_free_fd() >= before + 20
    del stores, store
    gc.collect()
    assert lowest_free_fd() == before
