"""dev/runtests.py runs below the lanes' editors and agents; the landing gate (`just gate`, TL_TEST_FULL=1) keeps its priority."""
from unittest import mock

import pytest
import runtests
import support.paths  # noqa: F401

CASES = [({}, 0, 10), ({}, 4, 6), ({}, 10, None), ({}, 15, None), ({"TL_TEST_FULL": "1"}, 0, None)]


@pytest.mark.parametrize(("env", "now", "raised_by"), CASES)
def test_the_runner_goes_down_to_nice_10_and_never_further_than_that(env, now, raised_by):
    with mock.patch.object(runtests.os, "nice", side_effect=lambda inc: now if inc == 0 else now + inc) as nice:
        runtests.lower_priority(env)
    raised = [c.args[0] for c in nice.call_args_list if c.args[0] != 0]
    assert raised == ([] if raised_by is None else [raised_by])
