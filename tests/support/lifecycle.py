"""Small lifecycle builder for tests that exercise close-out without the run root."""
from unittest import mock

from taskloop.adapters import deadline
from tlpipeline.lifecycle import Lifecycle


def lifecycle(host) -> Lifecycle:
    return Lifecycle(host, host, host, host, body=mock.Mock(), lease=mock.Mock(return_value=mock.Mock()),
                     reexecs=mock.Mock(), deadline=deadline.deadline)
