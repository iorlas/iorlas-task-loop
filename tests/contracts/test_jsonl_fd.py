"""A store that appended gives its descriptor back when it is dropped: a process that makes a store per test (or per run) must not run out
of descriptors (select() fails above 1024, then git cannot start: tests/slots/real failed at 1-2 xdist workers)."""
import gc
import os
from pathlib import Path

from taskloop.contracts.rotating import RotatingJsonl

SCAN = 1024


def held(inodes: set[int]) -> int:
    """How many open descriptors of this process are one of these files."""
    count = 0
    for fd in range(SCAN):
        try:
            count += os.fstat(fd).st_ino in inodes
        except OSError:
            continue
    return count


def test_a_dropped_store_closes_the_file_it_appended_to(workdir):
    paths = [Path(workdir, f"s{i}.jsonl") for i in range(20)]
    stores = [RotatingJsonl(p) for p in paths]
    for store in stores:
        store.append({"a": 1})
    inodes = {p.stat().st_ino for p in paths}
    assert held(inodes) == 20
    del stores, store
    gc.collect()
    assert held(inodes) == 0
