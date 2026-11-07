"""A change to task-loop or its dashboard runs no delegate test; a change to delegate (or the vendored packages it shares) runs them."""
from pathlib import Path

import pytest
from support import scope

ROOT = Path(__file__).resolve().parents[2]


def wanted(*args: str) -> bool:
    return scope.delegate_wanted(args, ROOT)


class TestDelegateScope:
    def test_a_taskloop_or_dashboard_change_skips_delegate(self, monkeypatch):
        monkeypatch.delenv("TL_DELEGATE_TESTS", raising=False)
        monkeypatch.setattr(scope, "changed_paths", lambda: {
            "src/taskloop/app/run/x.py", "packages/dash/src/tldash/y.py", "tests/land/test_z.py",
        })
        assert not wanted("tests")

    @pytest.mark.parametrize(
        "path", ["src/delegate/app/run.py", "tests/delegate/test_route.py", "skills/task-loop/_vendor/stream_proc/runner.py"]
    )
    def test_a_delegate_change_runs_delegate(self, monkeypatch, path):
        monkeypatch.delenv("TL_DELEGATE_TESTS", raising=False)
        monkeypatch.setattr(scope, "changed_paths", lambda: {path})
        assert wanted("tests")

    def test_an_unknown_base_runs_delegate_rather_than_skip_it_by_accident(self, monkeypatch):
        monkeypatch.delenv("TL_DELEGATE_TESTS", raising=False)
        monkeypatch.setattr(scope, "changed_paths", lambda: None)
        assert wanted("tests")

    def test_naming_the_folder_or_the_variable_runs_delegate(self, monkeypatch):
        monkeypatch.delenv("TL_DELEGATE_TESTS", raising=False)
        monkeypatch.setattr(scope, "changed_paths", set)
        assert wanted("tests/delegate/test_route.py::T::test_x")
        assert not wanted("tests/land")
        monkeypatch.setenv("TL_DELEGATE_TESTS", "1")
        assert wanted("tests/land")
