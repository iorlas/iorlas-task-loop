"""The engine close guard uses the host's startup base."""

from unittest import mock

import pytest

from taskloop.app.run import stages


def test_close_guard_uses_host_startup_base():
    host = mock.Mock()
    host.cfg.base = "origin/release"
    stopped = RuntimeError("stop at close guard construction")

    with (
        mock.patch.object(stages, "RunOnce"),
        mock.patch.object(stages, "guard_for", side_effect=stopped) as guard,
        pytest.raises(RuntimeError, match="stop at close guard construction"),
    ):
        stages.run_stages(host, "close", continuous=False)

    guard.assert_called_once()
    captured_base_of = guard.call_args.kwargs["base_of"]
    assert captured_base_of("any-repo", object()) == "origin/release"
    assert captured_base_of("different-repo", object()) == "origin/release"
