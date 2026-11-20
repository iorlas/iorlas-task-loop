"""Exercise the shared capability fixture in controlled in-process pytest sessions."""

import errno
import socket
from pathlib import Path
from types import TracebackType

import pytest

pytest_plugins = ("pytester",)


def probe_session(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, error_number: int | None, fail_at_bind: bool = False,
) -> tuple[pytest.RunResult, list[str]]:
    events: list[str] = []

    class Probe:
        def __enter__(self) -> Probe:
            return self

        def __exit__(
            self, error_type: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None,
        ) -> None:
            events.append("close")

        def bind(self, address: tuple[str, int]) -> None:
            assert address == ("127.0.0.1", 0)
            events.append("bind")
            if error_number is not None and fail_at_bind:
                raise OSError(error_number, "controlled socket failure")

    def create(family: int, kind: int) -> Probe:
        assert (family, kind) == (socket.AF_INET, socket.SOCK_STREAM)
        events.append("create")
        if error_number is not None and not fail_at_bind:
            raise OSError(error_number, "controlled socket failure")
        return Probe()

    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text())
    pytester.makepyfile('''
        def test_first(require_loopback):
            assert require_loopback is None

        def test_second(require_loopback):
            assert require_loopback is None

        def test_without_sockets():
            pass
    ''')
    with monkeypatch.context() as patch:
        patch.setattr(socket, "socket", create)
        result = pytester.runpytest_inprocess("-q", "-rs", "-p", "no:cacheprovider")
    return result, events


@pytest.mark.parametrize("error_number", [errno.EPERM, errno.EACCES])
@pytest.mark.parametrize("fail_at_bind", [False, True])
def test_permission_denial_skips_consumers_but_leaves_socket_free_tests_running(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, error_number: int, fail_at_bind: bool,
) -> None:
    result, events = probe_session(pytester, monkeypatch, error_number, fail_at_bind)
    result.assert_outcomes(passed=1, skipped=2)
    reason = f"Loopback TCP sockets unavailable in this environment: [Errno {error_number}] controlled socket failure"
    assert reason in result.stdout.str()
    assert events == (["create", "bind", "close"] if fail_at_bind else ["create"])


def test_allowed_loopback_runs_consumers_with_one_closed_probe(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, events = probe_session(pytester, monkeypatch, None)
    result.assert_outcomes(passed=3)
    assert events == ["create", "bind", "close"]


@pytest.mark.parametrize(("error_number", "fail_at_bind"), [(errno.EMFILE, False), (errno.EADDRINUSE, True)])
def test_unrelated_socket_errors_remain_errors(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, error_number: int, fail_at_bind: bool,
) -> None:
    result, events = probe_session(pytester, monkeypatch, error_number, fail_at_bind)
    result.assert_outcomes(passed=1, errors=2)
    assert "controlled socket failure" in result.stdout.str()
    assert "Loopback TCP sockets unavailable" not in result.stdout.str()
    assert events == (["create", "bind", "close"] if fail_at_bind else ["create"])
