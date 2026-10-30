"""The live kind: scenarios that run the real pieces (git, processes, docker, tl, the dashboard) and run only when asked for.

tests/conftest.py ignores this folder unless the run selects `-m live` (just test-live); here every test is marked `live` and
`real_proc` (the process guard is off: the real thing is the point), has an isolated HOME and config dir, and prints its wall time."""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401


def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/live/" in str(item.path):
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.real_proc("a live scenario runs the real processes"))


@pytest.fixture(autouse=True)
def wall_time(request):
    started = time.monotonic()
    yield
    print(f"\nLIVE {request.node.name}: {time.monotonic() - started:.1f} s wall")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A HOME, config dir and git identity of its own; the caller's uv cache and Python dir stay (a child `uv run` needs them)."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    keep = {"UV_CACHE_DIR": os.popen("uv cache dir").read().strip(), "UV_PYTHON_INSTALL_DIR": os.popen("uv python dir").read().strip()}
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "APPDATA": str(home / ".config"), "TMPDIR": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "CLAUDE_CODE_SESSION_ID": "live-0", **keep}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return home
