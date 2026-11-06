"""dev/runtests.py sizes its workers by the cores the other lanes leave free; the landing gate (TL_TEST_FULL) takes them all."""
import pytest
import runtests
import support.paths  # noqa: F401

BIG = 5000


@pytest.mark.parametrize(("busy", "n"), [(0, 4), (1, 3), (2, 2), (3, 2), (4, 2), (20, 2)])
def test_a_busy_host_earns_a_lane_fewer_workers_but_never_fewer_than_two_for_a_wide_selection(busy, n):
    assert runtests.workers(BIG, cpus=4, mem_mb=64 * 1024, busy=busy) == n


def test_a_small_selection_on_a_busy_host_runs_in_one_process():
    assert runtests.workers(100, cpus=4, mem_mb=64 * 1024, busy=20) == 1


@pytest.mark.parametrize("busy", [0, 3, 20])
def test_the_landing_gate_takes_every_core_however_busy_the_host_is(busy):
    assert runtests.workers(BIG, cpus=4, mem_mb=64 * 1024, busy=busy, full=True) == 4
