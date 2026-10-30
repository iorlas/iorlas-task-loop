"""pytest wiring: per-worker isolation for `pytest -n N`, the address-space cap and the serial group."""
import contextlib
import ctypes
import os
import resource
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim

# Tests that must not share a clock, a port, a lock or a process group with another test running at the same moment: they are marked
# `serial`, and the release gate runs them in ONE process after the parallel workers (`-m "not serial"`, then `-m serial`).
SERIAL = {
    "test_write_idle": "starts real worker process groups and asserts how long a writer stays idle against the wall clock",
}
# The release gate sets TL_WORKER_MB. A healthy worker peaks near 430 MB; a runaway test gets MemoryError, not the host's RAM.
WORKER_MB = int(os.environ.get("TL_WORKER_MB") or 2048)


def pytest_collection_modifyitems(items):
    for item in items:
        if item.module.__name__ in SERIAL:
            item.add_marker(pytest.mark.serial)


def pytest_ignore_collect(collection_path, config):
    """tests/live (the explicit-only kind) is collected only by a run that selects `-m live` (just test-live): never by the default run,
    just test-fast or the release suite, whose `-m` is something else."""
    if "live" in collection_path.relative_to(Path(__file__).parent).parts[:1]:
        expr = (config.getoption("markexpr", "") or "").split()
        return not ("live" in expr and "not" not in expr)
    return None


@pytest.fixture(autouse=True)
def procs(request):
    """The process sim of this test (tests/support/procsim.py): fakes answer the checks, a real spawn fails the test unless it is marked
    `real_proc` (git is the gitsim's, or a `real_git` test's)."""
    world = procsim.Procs(request.node.nodeid, guarded=request.node.get_closest_marker("real_proc") is None)
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield world
    world.check()


def cap_memory(megabytes):
    """Linux only (macOS does not enforce RLIMIT_AS): cap this process's address space, and its children's each; a lower cap stays."""
    limit = megabytes << 20
    with contextlib.suppress(OSError, ValueError):
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if sys.platform.startswith("linux") and (soft == resource.RLIM_INFINITY or soft > limit):
            resource.setrlimit(resource.RLIMIT_AS, (limit if hard == resource.RLIM_INFINITY else min(limit, hard), hard))


def isolate(home):
    """Its own HOME, config dir and temp dir; the real git config is copied in, since tests commit with the identity it holds."""
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    real = Path.home() / ".gitconfig"
    if real.is_file():
        (home / ".gitconfig").write_bytes(real.read_bytes())
    os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), TMPDIR=str(home / "tmp"))
    tempfile.tempdir = None


def pytest_configure(config):
    if not hasattr(config, "workerinput"):  # the controller (or a plain run) keeps the caller's environment
        return
    if sys.platform.startswith("linux"):
        with contextlib.suppress(OSError, AttributeError):
            ctypes.CDLL(None, use_errno=True).prctl(1, 9, 0, 0, 0)  # PR_SET_PDEATHSIG, SIGKILL: a worker leaves with its controller
    cap_memory(WORKER_MB)
    home = Path(tempfile.mkdtemp(prefix="tl-worker-"))
    config._worker_home = home
    isolate(home)


def pytest_unconfigure(config):
    home = getattr(config, "_worker_home", None)
    if home:
        shutil.rmtree(home, ignore_errors=True)
