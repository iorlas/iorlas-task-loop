"""dev/runtests.py shares the box: it runs below the lanes' editors and agents, and takes no more workers than the load leaves free; the
landing gate (`just gate`, TL_TEST_FULL=1) keeps the cores."""
from unittest import mock

import pytest
import runtests
import support.paths  # noqa: F401


@pytest.mark.parametrize(("load", "expected"), [(None, 4), (0.0, 4), (10.4, 3), (13.2, 2), (40.0, 2)])
def test_the_workers_are_what_the_load_leaves_free_of_the_cores(load, expected):
    assert runtests.workers(10_000, cpus=14, mem_mb=64_000, load=load) == expected


def test_a_small_selection_takes_one_worker_and_a_big_one_never_fewer_than_two_however_loaded_the_box_is():
    assert runtests.workers(10, cpus=14, mem_mb=64_000, load=99.0) == 1
    assert runtests.workers(151, cpus=14, mem_mb=64_000, load=99.0) == 2


def test_the_load_is_ignored_for_the_gate():
    with mock.patch.object(runtests.os, "getloadavg", return_value=(30.0, 0.0, 0.0)) as read:
        assert runtests.current_load({"TL_TEST_FULL": "1"}) is None
        read.assert_not_called()
        assert runtests.current_load({}) == 30.0


CASES = [({}, 0, 10), ({}, 4, 6), ({}, 10, None), ({}, 15, None), ({"TL_TEST_FULL": "1"}, 0, None)]


@pytest.mark.parametrize(("env", "now", "raised_by"), CASES)
def test_the_runner_goes_down_to_nice_10_and_never_further_than_that(env, now, raised_by):
    with mock.patch.object(runtests.os, "nice", side_effect=lambda inc: now if inc == 0 else now + inc) as nice:
        runtests.lower_priority(env)
    raised = [c.args[0] for c in nice.call_args_list if c.args[0] != 0]
    assert raised == ([] if raised_by is None else [raised_by])
