"""The delegate tests import their helpers (hermetic, routing_support, run_support) by flat name: this folder is on sys.path for them.
Every test runs in a home of its own (hermetic.home): HOME, XDG, CODEX_HOME and DELEGATE_CONFIG_DIR point into a fresh temp dir."""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from any_agent import procs as shelf_procs
from any_agent import supervisor

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ENV = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CODEX_HOME", "DELEGATE_CONFIG_DIR", "TMPDIR")
_collector_env = {k: os.environ.get(k) for k in ENV}
import hermetic  # noqa: E402

# hermetic points the process at its own home on import; the other slices collected in this worker keep the worker's (their temp dir
# is what the loop and slots tests build repos under), and each delegate test gets its home from own_home below
for _k, _v in _collector_env.items():
    os.environ.pop(_k, None) if _v is None else os.environ.__setitem__(_k, _v)


@pytest.fixture(scope="session", autouse=True)
def worker_clis():
    """codex, claude and opencode answer `--version` from a folder of ours, first on PATH: a test that probes the worker CLIs spawns the
    same processes on a host with none installed and on one with all three."""
    bin_dir = Path(hermetic.ROOT) / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("codex", "claude", "opencode"):
        exe = bin_dir / name
        exe.write_text(f'#!/bin/sh\necho "{name} 0.0.0-test"\n')
        exe.chmod(0o755)
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{saved}"
    yield
    os.environ["PATH"] = saved


@pytest.fixture(autouse=True)
def own_home():
    saved = {k: os.environ.get(k) for k in ENV}
    tempfile.gettempdir()  # cache the outer temp dir before TMPDIR moves into this home
    d = tempfile.mkdtemp(prefix="t-", dir=hermetic.ROOT)
    hermetic.home(d)
    try:
        yield
    finally:
        tempfile.tempdir = None
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch):
    """The supervisor looks at its worker every POLL_S and a stop waits GRACE_S between SIGTERM and SIGKILL: both are the library's
    defaults for a real worker (0.5 s, 5 s), not what a test asserts, so a test waits a tenth of that."""
    monkeypatch.setattr(supervisor, "POLL_S", 0.05)
    monkeypatch.setattr(shelf_procs, "GRACE_S", 0.5)
