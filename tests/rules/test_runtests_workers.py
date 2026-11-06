"""dev/runtests.py sizes its workers by the cores the other lanes leave free, so lanes running together do not starve each other."""
import pytest
import runtests
import support.paths  # noqa: F401


@pytest.mark.parametrize(("busy", "n"), [(0, 4), (1, 3), (2, 2), (3, 1), (4, 1), (20, 1)])
def test_a_busy_host_earns_fewer_workers_and_never_fewer_than_one(busy, n):
    assert runtests.workers(5000, cpus=4, mem_mb=64 * 1024, busy=busy) == n
