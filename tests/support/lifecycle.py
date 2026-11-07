"""Small lifecycle builder for tests that exercise close-out without the run root."""
from unittest import mock

from taskloop.adapters import deadline
from taskloop.app.pipeline.lifecycle import Lifecycle, LifecycleHost


def lifecycle(host: LifecycleHost) -> Lifecycle:
    return Lifecycle(host, body=mock.Mock(), lease=mock.Mock(return_value=mock.Mock()), reexecs=mock.Mock(), deadline=deadline.deadline)
