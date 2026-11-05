"""pytest wiring: per-worker isolation for `pytest -n N`, the address-space cap, the serial group and the three test kinds.

A test's kind comes from its path, never from a hand marker: a file under tests/e2e/ is `e2e` (a whole flow), a file under a `real/`
folder (tests/<slice>/real/) is `real` (real git, processes or sockets), anything else is logic (fakes, in process, fast). The older
`@real_proc(reason)` and `@real_git(reason)` marks on a single test fold into `real`. Guards (tests/support/procsim.py): a logic test that
spawns, forks or runs real git fails; a `real` test that never spawns fails. A test over its kind's time limit fails (LIMITS_S)."""
import contextlib
import ctypes
import importlib
import inspect
import os
import pkgutil
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Bytecode is cached even when the caller says not to (Claude Code exports PYTHONDONTWRITEBYTECODE=1): without it every xdist worker and
# every Python a test starts compiles every module again (about 2 s of each worker's collection). The cache sits outside the tree, under
# the temp dir (mirrored absolute paths, so worktrees never share a file); set before any of ours is imported, and for the children too.
PYCACHE = Path(tempfile.gettempdir()) / f"tl-pycache-{os.getuid()}"
sys.dont_write_bytecode = False
sys.pycache_prefix = str(PYCACHE)
os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
os.environ["PYTHONPYCACHEPREFIX"] = str(PYCACHE)

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.register_assert_rewrite("support")  # the helpers of tests/support assert too: show the operands, as in a test file
import support.paths  # noqa: E402, F401  (ROOT/src on sys.path; after the bytecode setup above)
from support import procsim  # noqa: E402
from support.scope import delegate_wanted  # noqa: E402

from taskloop.contracts import factorydb  # noqa: E402


def preload_src():
    """Import every module of the package now, at collection, not inside the first test a worker runs: the engine imports about 200 of them
    lazily, and on a loaded host that cold import alone (1.5 s to 3 s) put the first engine test of each worker over its logic limit."""
    package = importlib.import_module("taskloop")
    for found in pkgutil.walk_packages(package.__path__, "taskloop."):
        importlib.import_module(found.name)


preload_src()
KIND = pytest.StashKey[str]()
SKIPPED = pytest.StashKey[bool]()

# Tests that must not share a clock, a port, a lock or a process group with another test running at the same moment: they are marked
# `serial`, and the release gate runs them in ONE process after the parallel workers (`-m "not serial"`, then `-m serial`).
SERIAL = {
    "test_write_idle": "starts real worker process groups and asserts how long a writer stays idle against the wall clock",
}
# The release gate sets TL_WORKER_MB. A healthy worker peaks near 430 MB; a runaway test gets MemoryError, not the host's RAM.
WORKER_MB = int(os.environ.get("TL_WORKER_MB") or 2048)


# Seconds a test's call may take, by kind, set from measured runs under 8 xdist workers (2026-10-30): logic max 1.4 s (the gitsim engine
# tests; 311 of 2261 pass 0.2 s, the target the limit comes down to as they speed up), real max 4.4 s, e2e max 2.5 s.
# TL_TIME_SCALE multiplies them. A logic test is limited by the CPU time its call used (a loaded host stretches the wall clock, not the CPU
# time), with a wall backstop of WALL_FACTOR times the limit for a test that sleeps or waits; the other kinds spawn processes, so wall time.
WALL_FACTOR = 10
LIMITS_S = {"logic": 2.0, "real": 15.0, "e2e": 30.0, "live": 3600.0}
RULES_LIMIT_S = 15.0
TESTS_DIR = Path(__file__).resolve().parent


def kind_of(item) -> str:
    """logic / real / e2e: by path first (tests/e2e/..., tests/<slice>/real/...), then a single test's own real_proc / real_git mark."""
    here = Path(str(item.path)).resolve()
    if TESTS_DIR not in here.parents:  # this file loaded as a plugin (-p conftest) into a tree that is not ours
        return "logic"
    parts = here.relative_to(TESTS_DIR).parts
    if parts[0] in ("e2e", "live"):  # live (tests/live, explicit-only) runs the real pieces: no guard, no limit
        return parts[0]
    func = getattr(item, "obj", None)
    if "real" in parts[:-1] or item.get_closest_marker("real_proc") or getattr(func, "real_git", None):
        return "real"
    return "logic"


def pytest_collection_modifyitems(items):
    for item in items:
        if item.module.__name__.rpartition(".")[2] in SERIAL:
            item.add_marker(pytest.mark.serial)
        kind = kind_of(item)
        item.stash[KIND] = kind
        if kind not in ("logic", "live"):  # live tests carry their own marker
            item.add_marker(getattr(pytest.mark, kind))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A test whose call ran past its kind's limit fails, with the limit and the time in the message."""
    outcome = yield
    report = outcome.get_result()
    if call.when == "call" and report.skipped:
        item.stash[SKIPPED] = True  # a skipped test spawned nothing, and a real one is not failed for it
    limit = LIMITS_S[item.stash.get(KIND, "logic")] * float(os.environ.get("TL_TIME_SCALE") or 1)
    if (TESTS_DIR / "rules") in Path(str(item.path)).parents:
        limit = max(limit, RULES_LIMIT_S)  # the gate's rules read the whole tree
    limit = max(limit, getattr(item.module, "LIMIT_S", 0))  # a module that says why it is heavier (a simulation) names its own
    logic = item.stash.get(KIND, "logic") == "logic"
    used, wall = (item.stash.get(CPU_S, call.duration) if logic else call.duration), call.duration
    if call.when == "call" and report.passed and (used > limit or (logic and wall > limit * WALL_FACTOR)):
        report.outcome = "failed"
        report.longrepr = (f"{item.nodeid}: a {item.stash.get(KIND, 'logic')} test took {used:.2f} s of {'CPU' if logic else 'wall'} time"
                           f" ({wall:.2f} s wall), over its {limit:.2f} s limit")


def pytest_ignore_collect(collection_path, config):
    """tests/live (the explicit-only kind) is collected only by a run that selects `-m live` (just test-live): never by the default run,
    just test-fast or the release suite, whose `-m` is something else. tests/delegate is collected only when the change touches delegate
    (tests/support/scope.py): a change to task-loop or its dashboard runs none of them."""
    if "live" in collection_path.relative_to(Path(__file__).parent).parts[:1]:
        expr = (config.getoption("markexpr", "") or "").split()
        return not ("live" in expr and "not" not in expr)
    if "delegate" in collection_path.relative_to(Path(__file__).parent).parts[:1]:
        return not delegate_wanted(config.args, Path(config.invocation_params.dir))
    return None


def pytest_pycollect_makeitem(collector, name, obj):
    """A test module collects the classes it defines, never the ones it imports (a base or mixin from tests/support, a class under test)."""
    if isinstance(collector, pytest.Module) and inspect.isclass(obj) and obj.__module__ != collector.obj.__name__:
        return []
    return None


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_setup(item):
    """unittest's setUp ran in the test's own phase; setup_method runs in pytest's setup phase, and pytest swaps sys.stdout / sys.stderr at
    the start of every phase. A patch of either made while setting up (mock.patch of sys.stdout, a redirect) is carried into the call."""
    before = sys.stdout, sys.stderr
    try:
        return (yield)
    finally:
        item.stash[_SETUP_STD] = tuple(now if now is not was else None for was, now in zip(before, (sys.stdout, sys.stderr), strict=True))


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item):
    patched = item.stash.get(_SETUP_STD, (None, None))
    own = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = (p or o for p, o in zip(patched, own, strict=True))
    cpu = time.process_time()
    try:
        return (yield)
    finally:
        sys.stdout, sys.stderr = own
        item.stash[CPU_S] = time.process_time() - cpu


_SETUP_STD = pytest.StashKey[tuple]()
CPU_S = pytest.StashKey[float]()


@pytest.fixture(autouse=True)
def case_helpers(request, procs):
    """The unittest names the plain test classes still use: self.addCleanup (runs last-in-first-out after the test and its teardown_method),
    self.enterContext, self.subTest (pytest's `subtests`), self._testMethodName and self.id(). It depends on `procs` so that the cleanups,
    which undo patches made in setup_method on top of the process sim, run before the sim is uninstalled."""
    case = request.instance
    if case is None:
        yield
        return
    with contextlib.ExitStack() as stack:
        case._testMethodName = request.node.originalname
        case.id = lambda: request.node.nodeid
        case.addCleanup = stack.callback
        case.enterContext = stack.enter_context

        @contextlib.contextmanager
        def sub_test(msg=None, **params):
            """pytest's subtest swaps sys.stdout and sys.stderr for its own capture and puts its own back at the end: keep the test's."""
            streams = sys.stdout, sys.stderr
            try:
                with request.getfixturevalue("subtests").test(msg, **params):
                    sys.stdout, sys.stderr = streams
                    yield
            finally:
                sys.stdout, sys.stderr = streams
        case.subTest = sub_test
        yield


@pytest.fixture(autouse=True)
def filesystem_cache():
    """Tests must not inherit connections or patched mount verdicts."""
    factorydb.close_shared()
    factorydb.clear_filesystem_cache()
    yield
    factorydb.close_shared()
    factorydb.clear_filesystem_cache()


@pytest.fixture(autouse=True)
def procs(request):
    """The process sim of this test (tests/support/procsim.py): fakes answer the checks, a real spawn (git too) fails a logic test, and a
    `real` test that spawned nothing fails."""
    kind = request.node.stash.get(KIND, "logic")
    world = procsim.Procs(request.node.nodeid, guarded=kind == "logic")
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield world
    world.check(must_spawn=kind == "real" and not request.node.stash.get(SKIPPED, False))


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
