"""pytest wiring: per-process isolation, the worker address-space cap, the serial group and the three test kinds.

A test's kind comes from its path, never from a hand marker: a file under tests/e2e/ is `e2e` (a whole flow), a file under a `real/`
folder (tests/<slice>/real/ or packages/<stage>/tests/real/) is `real` (real git, processes or sockets), anything else is logic (fakes,
in process, fast). A single test's `@needs(capability, reason)` (or the older `@real_proc(reason)` / `@real_git(reason)`) folds into
`real`. Guards (packages/testkit/src/tltestkit/procsim.py): a logic test that spawns, forks or runs real git fails; a `real` test that
never spawns fails.
A test over its kind's time limit fails (tltestkit.limits)."""
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
import threading
import time
from pathlib import Path

import pytest

from tltestkit.case import install_case_helpers
from tltestkit.wall import wall_guard

REAL_HOME = os.environ.get("HOME", "")
REAL_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", str(Path(REAL_HOME) / ".config"))
os.environ.setdefault("TL_TEST_REAL_HOME", REAL_HOME)
os.environ.setdefault("TL_TEST_REAL_CONFIG_HOME", REAL_CONFIG_HOME)

# Bytecode is cached even when the caller says not to (Claude Code exports PYTHONDONTWRITEBYTECODE=1): without it every xdist worker and
# every Python a test starts compiles every module again (about 2 s of each worker's collection). The cache sits outside the tree, under
# the temp dir (mirrored absolute paths, so worktrees never share a file); set before any of ours is imported, and for the children too.
PYCACHE = Path(tempfile.gettempdir()) / f"tl-pycache-{os.getuid()}"
sys.dont_write_bytecode = False
sys.pycache_prefix = str(PYCACHE)
os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
os.environ["PYTHONPYCACHEPREFIX"] = str(PYCACHE)

# The temp dir by its real path: macOS's $TMPDIR is under /var, a symlink to /private/var, and code that resolves a path (tl does, for the
# repo and the lock names; a child's getcwd does) would otherwise name the same directory differently from the test that made it.
os.environ["TMPDIR"] = tempfile.tempdir = os.path.realpath(tempfile.gettempdir())

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest.register_assert_rewrite("support")  # the helpers of tests/support assert too: show the operands, as in a test file
import support.paths  # noqa: E402, F401  (ROOT/src on sys.path; after the bytecode setup above)
from support.scope import delegate_wanted  # noqa: E402

from taskloop.adapters import procs  # noqa: E402
from taskloop.app.parts import STAGE_PARTS  # noqa: E402
from tlkernel import factorydb, scratch  # noqa: E402
from tltestkit import procsim, work  # noqa: E402
from tltestkit.limits import hang_s, kind_of_parts, limit_for  # noqa: E402

procsim.SHELL_PROCESS_ADAPTERS.append(procs)
factorydb.declare_parts(STAGE_PARTS, complete=True)


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
    "test_work_boundary": "spawns the pinned import-linter through uv; two copies at once on a cold uv cache crashed it with exit -11",
    "test_write_idle": "starts real worker process groups and asserts how long a writer stays idle against the wall clock",
}
# The release gate sets TL_WORKER_MB. A healthy worker peaks near 430 MB; a runaway test gets MemoryError, not the host's RAM.
WORKER_MB = int(os.environ.get("TL_WORKER_MB") or 2048)


# The limits and the kind of a test by its path are tltestkit.limits (packages/testkit): every package inherits them, none copies them.
TESTS_DIR = Path(__file__).resolve().parent


def kind_of(item) -> str:
    """logic / real / e2e: by path first (tests/e2e/..., tests/<slice>/real/...), then a single test's own real_proc / real_git mark."""
    here = Path(str(item.path)).resolve()
    if TESTS_DIR not in here.parents:  # this file loaded as a plugin (-p conftest) into a tree that is not ours
        return "logic"
    func = getattr(item, "obj", None)
    marked = bool(item.get_closest_marker("real_proc") or item.get_closest_marker("needs") or getattr(func, "real_git", None))
    return kind_of_parts(here.relative_to(TESTS_DIR).parts, marked_real=marked)


def quarantined_ids():
    path = TESTS_DIR / "quarantine.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return {s for s in (line.strip() for line in lines) if s and not s.startswith("#")}


def pytest_collection_modifyitems(items):
    held = quarantined_ids()
    for item in items:
        if held and item.nodeid in held:
            item.add_marker(pytest.mark.quarantine)
        if item.module.__name__.rpartition(".")[2] in SERIAL:
            item.add_marker(pytest.mark.serial)
        kind = kind_of(item)
        item.stash[KIND] = kind
        if kind not in ("logic", "live"):  # live tests carry their own marker
            item.add_marker(getattr(pytest.mark, kind))


def test_limit(item):
    return limit_for(item.stash.get(KIND, "logic"), rules=(TESTS_DIR / "rules") in Path(str(item.path)).parents,
                     module_limit=getattr(item.module, "LIMIT_S", 0))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A test whose call ran past its kind's limit fails, with the limit and the time in the message."""
    outcome = yield
    report = outcome.get_result()
    if call.when == "call" and report.skipped:
        item.stash[SKIPPED] = True  # a skipped test spawned nothing, and a real one is not failed for it
    limit = test_limit(item)
    kind, wall = item.stash.get(KIND, "logic"), call.duration
    if CPU_S not in item.stash:  # a subtest's own report, made inside the call: the whole call is judged when it ends
        return
    used = item.stash.get(WORK_S, item.stash[CPU_S]) if kind == "logic" else item.stash[CPU_S]
    hang = hang_s(limit, float(os.environ.get("TL_TIME_SCALE") or 1))
    if call.when == "call" and report.passed and (used > limit or wall > hang):
        report.outcome = "failed"
        why = f"over its {limit:.2f} s limit" if used > limit else f"over the {hang:.0f} s a test may take before it counts as hung"
        report.longrepr = (f"{item.nodeid}: a {kind} test took {used:.2f} s of work ({item.stash[CPU_S]:.2f} s of CPU, {wall:.2f} s wall),"
                           f" {why}")


def pytest_ignore_collect(collection_path, config):
    """tests/live (the explicit-only kind) is collected only by a run that selects `-m live` (just test-live): never by the default run,
    `just test` or the release gate, whose `-m` is something else. tests/delegate is collected only when the change touches delegate
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
        with test_wall_guard(item):
            return (yield)
    finally:
        item.stash[_SETUP_STD] = tuple(now if now is not was else None for was, now in zip(before, (sys.stdout, sys.stderr), strict=True))


def test_wall_guard(item):
    return contextlib.nullcontext() if item.stash.get(KIND, "logic") == "live" else wall_guard(
        hang_s(test_limit(item), float(os.environ.get("TL_TIME_SCALE") or 1)), item.nodeid)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_teardown(item):
    with test_wall_guard(item):
        return (yield)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item):
    patched = item.stash.get(_SETUP_STD, (None, None))
    own = sys.stdout, sys.stderr
    cpu, instr = cpu_s(), work.instructions()
    try:
        with test_wall_guard(item):
            sys.stdout, sys.stderr = (p or o for p, o in zip(patched, own, strict=True))
            return (yield)
    finally:
        sys.stdout, sys.stderr = own
        item.stash[CPU_S] = cpu_s() - cpu
        done = work.instructions()
        if work.measured() and instr is not None and done is not None:
            item.stash[WORK_S] = work.seconds(done - instr)


def cpu_s() -> float:
    """CPU seconds this process has used, plus those of the children it has waited for."""
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + kids.ru_utime + kids.ru_stime


_SETUP_STD = pytest.StashKey[tuple]()
CPU_S = pytest.StashKey[float]()
WORK_S = pytest.StashKey[float]()


@pytest.fixture(autouse=True)
def no_leaked_threads(filesystem_cache, procs):
    """A thread a test started and left running (a Lease heartbeat nobody stopped and joined) goes on using the stores the test's teardown
    closes, and crashes the worker in sqlite3 later, in another test: the test that leaked it fails instead. It requests the fixtures that
    close those stores so that it is checked before they are undone."""
    before = set(threading.enumerate())
    yield
    left = [t for t in threading.enumerate() if t not in before]
    for t in left:
        t.join(0.5)
    left = [t.name for t in left if t.is_alive()]
    assert not left, f"the test left threads running: {left}; stop and join them before it ends"


@pytest.fixture(autouse=True)
def case_helpers(request, procs, no_leaked_threads):
    """The unittest names the plain test classes still use: self.addCleanup (runs last-in-first-out after the test and its teardown_method),
    self.enterContext, self.subTest (pytest's `subtests`), self._testMethodName and self.id(). It depends on `procs` so that the cleanups,
    which undo patches made in setup_method on top of the process sim, run before the sim is uninstalled."""
    with install_case_helpers(request):
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
    """The process sim of this test (packages/testkit/src/tltestkit/procsim.py): fakes answer the checks, a real spawn (git too) fails
    a logic test, and a `real` test that spawned nothing fails."""
    kind = request.node.stash.get(KIND, "logic")
    world = procsim.Procs(request.node.nodeid, guarded=kind == "logic")
    with contextlib.ExitStack() as stack:
        world.install(stack)
        yield world
    # a delegate test reaches its process through a worker CLI it probes (codex, claude, opencode): a host with none has nothing to spawn
    no_cli = request.node.nodeid.startswith("tests/delegate/") and not any(map(shutil.which, ("codex", "claude", "opencode")))
    world.check(must_spawn=kind == "real" and not request.node.stash.get(SKIPPED, False) and not no_cli)


@pytest.fixture(autouse=True)
def keep_tempdir_cache():
    """A test that points TMPDIR into a folder it removes (the doctor tests) must not leave `tempfile.tempdir` cached on it: every later
    `tempfile` call without `dir=` in this worker would raise FileNotFoundError."""
    saved = tempfile.tempdir
    yield
    tempfile.tempdir = saved


@pytest.fixture
def workdir():
    """A scratch folder (contracts/scratch.py) on the checkout's disk, for the length of the test: the one place a test writes."""
    with scratch.scratch(os.environ, "wd-") as folder:
        yield folder


def cap_memory(megabytes):
    """Linux only (macOS does not enforce RLIMIT_AS): cap this process's address space, and its children's each; a lower cap stays."""
    limit = megabytes << 20
    with contextlib.suppress(OSError, ValueError):
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if sys.platform.startswith("linux") and (soft == resource.RLIM_INFINITY or soft > limit):
            resource.setrlimit(resource.RLIMIT_AS, (limit if hard == resource.RLIM_INFINITY else min(limit, hard), hard))


def isolate(home):
    """Its own HOME, config dir and temp dir; the test git identity (contracts/scratch.py) is written in, never the host's."""
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    scratch.write_git_config(home)
    os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), TMPDIR=str(home / "tmp"))
    tempfile.tempdir = None


def pytest_configure(config):
    work.calibrate()  # this host's speed at its best, to turn a logic test's instructions into seconds
    if hasattr(config, "workerinput"):
        if sys.platform.startswith("linux"):
            with contextlib.suppress(OSError, AttributeError):
                ctypes.CDLL(None, use_errno=True).prctl(1, 9, 0, 0, 0)  # PR_SET_PDEATHSIG, SIGKILL: a worker leaves with its controller
        cap_memory(WORKER_MB)
    home = scratch.scratch_dir(os.environ, "tl-run-")
    config._home = home
    isolate(home)


def pytest_sessionstart(session):
    """Refuse to collect or execute tests with the caller's home or config directory."""
    for name, original in (("HOME", REAL_HOME), ("XDG_CONFIG_HOME", REAL_CONFIG_HOME)):
        current = os.environ.get(name)
        if not current or Path(current).resolve() == Path(original).resolve():
            raise pytest.UsageError(f"test isolation failed: {name} still points at the caller's directory")


def pytest_unconfigure(config):
    home = getattr(config, "_home", None)
    if home:
        shutil.rmtree(home, ignore_errors=True)
