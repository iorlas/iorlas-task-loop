"""`just test`: run the tests the change can break (dev/affected.py picks them), nothing else. Exit 0 green, pytest's code otherwise.

    python3 dev/runtests.py

Workers: min(cpus, free RAM / 2 GB, ceil(tests / 150), 4). A selection of 150 tests or fewer runs in this one pytest process, no xdist.
The run goes down to nice 10 first, so a box shared by many lanes keeps its editors and landing gates responsive; TL_TEST_FULL=1 (set by
`just gate`, the landing gate) keeps the priority it was given.
TL_GREEN_LEDGER=1 (off by default): tests whose own files are unchanged since a green run are left out (dev/affected.py, the ledger), and
a fully green run records the tests that ran. The worker count is NOT reduced by the load: fewer workers expose test
pollution (tests/slots/real fail with `git rev-parse exited 128` at 2 workers, pass at 4 and alone).
Isolation: the run has its own HOME, config and temp dirs (under the scratch root, src/taskloop/contracts/scratch.py; the test
git identity, not the host's); xdist workers take one each on top
(tests/conftest.py). The tests marked `serial` run alone, after the parallel ones, and only those the selection holds.
Whole-suite runs are `just test-full`, started by a person; this script has no such mode. Standard library only.
"""
import ast
import importlib.util
import math
import os
import shutil
import signal
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "skills" / "task-loop" / "_vendor"))  # the vendored shelf packages
import affected
import stream_proc
import testtimes_report


def load_scratch():
    """src/taskloop/contracts/scratch.py by path: the owner of scratch paths and the test git identity, without the package."""
    path = Path(__file__).resolve().parent.parent / "src" / "taskloop" / "contracts" / "scratch.py"
    spec = importlib.util.spec_from_file_location("scratch", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scratch = load_scratch()

CHUNK = 150          # tests per worker: a worker costs ~2 s to start and a few hundred MB, so a smaller share is not worth one
MAX_WORKERS = 4      # the box also runs the implementer workers; the tests must not starve them
WORKER_MB = 2048     # RAM budget of one worker
WALL_S = 3600.0      # a hang guard for one pytest run (a wide selection takes 15 min in 4 workers); its process tree is killed
IDLE_S = 600.0       # a pytest run prints a dot per finished test: this long with none is a hung test, stopped long before WALL_S
NO_TESTS = 5         # pytest's exit code for "no tests collected" (a selection without a serial test)
WIDE = 0.5          # a selection above this share of all tests is a finding: the change reaches too far
LEDGER = "TL_GREEN_LEDGER"  # set: the green-test ledger is read and written
FULL = "TL_TEST_FULL"  # set: the landing gate, which takes the cores it is given
NICE = 10
DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONPATH")


def ledger_path(environ):
    """The ledger file when TL_GREEN_LEDGER is set, else None (the ledger is off)."""
    return affected.ledger_path(None, environ) if environ.get(LEDGER) else None


def pending(repo, tests, ledger, tracked=None):
    """`tests` without the ones already green on their own files (all of them when the ledger is off)."""
    return list(tests) if ledger is None else affected.not_green(repo, tests, ledger, tracked)


def record(repo, tests, ledger, codes, tracked=None):
    """After a run: its tests are green when every pytest exit code was 0 or 'no tests collected'; a red run records nothing."""
    if ledger is not None and tests and all(code in (0, NO_TESTS) for code in codes):
        affected.mark_green(repo, [t for t in tests if not t.startswith(affected.ALWAYS + "/")], ledger, tracked)


def count_tests(root, paths):
    """The test functions in `paths`, counted from the syntax trees (a parametrized test counts once)."""
    total = 0
    for path in paths:
        tree = ast.parse((Path(root) / path).read_text(encoding="utf-8"))
        total += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test") for n in ast.walk(tree))
    return total


def total_mb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (OSError, ValueError):
        return None


def lower_priority(environ):
    """Down to nice NICE, never further (an engine-run check is there already): the lanes' runs yield to the landing gate."""
    if environ.get(FULL):
        return
    now = os.nice(0)
    if now < NICE:
        os.nice(NICE - now)


def workers(n_tests, cpus=None, mem_mb=None):
    """How many pytest workers this selection earns on this host (1: no xdist)."""
    cpu = cpus if cpus is not None else (os.cpu_count() or 1)
    ram = mem_mb if mem_mb is not None else total_mb()
    return max(1, min(cpu, cpu if ram is None else ram // WORKER_MB, math.ceil(n_tests / CHUNK), MAX_WORKERS))


def isolated_env(home):
    """The environment of the run: its own HOME, config and temp dirs; the real git config copied in, since tests commit with it."""
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    scratch.write_git_config(home)
    # GIT_CONFIG_*: a release's core.hooksPath would fire tl's pre-push judge in the tests' repos
    env = {k: v for k, v in os.environ.items() if k not in DROP and not k.startswith("GIT_CONFIG_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), TMPDIR=str(home / "tmp"),
               TL_SCRATCH=str(home / "tmp"),  # a worker's home beside TMPDIR, not under .config (tests/delegate/hermetic.py)
               TL_WORKER_MB=str(WORKER_MB),
               TL_TEST_TIMES=str(home / "times-%p.json"), PYTHONPATH=str(Path(__file__).resolve().parent))  # dev/testtimes.py records
    return env


def pytest(root, env, mark, tests, n):
    """One pytest run in a session of its own; the wall limit, an interrupt or SIGTERM stop it with its workers (stream_proc). Exit code."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", "-p", "testtimes", "-o", "faulthandler_timeout=300",
            *(["-n", str(n)] if n > 1 else []), "-m", mark, *tests]

    def term(signum, _frame):
        raise SystemExit(128 + signum)
    old = signal.signal(signal.SIGTERM, term)
    try:
        res = stream_proc.run(argv, cwd=root, env=env, timeout=WALL_S, idle=IDLE_S, on_stdout=lambda t: print(t, end="", flush=True),
                              on_stderr=lambda t: print(t, end="", file=sys.stderr, flush=True))
    finally:
        signal.signal(signal.SIGTERM, old)
    if res.timed_out == "idle":
        print(f"runtests: no output for {IDLE_S:.0f} s (run {res.secs:.0f} s): a test hung; its process tree was killed", file=sys.stderr)
        return 124
    if res.timed_out:
        print(f"runtests: stopped after {WALL_S:.0f} s; its process tree was killed", file=sys.stderr)
        return 124
    return res.returncode if res.returncode is not None else 128 + (res.signal or 0)


def wide_note(root, n_tests):
    """'' or one line when the selection holds more than WIDE of all the tests (tests/delegate too)."""
    tests = Path(root) / "tests"
    files = [p.relative_to(root).as_posix() for p in tests.rglob("test_*.py")]
    total = count_tests(root, files)
    if total and n_tests > WIDE * total:
        return (f"runtests: the selection is {n_tests} of {total} tests ({100 * n_tests // total}%): "
                "this change reaches too far (a contract or the justfile?)")
    return ""


def main():
    root = Path(__file__).resolve().parent.parent
    lower_priority(os.environ)
    base = affected.base_of(root)
    repo = affected.Repo(root)
    ledger = ledger_path(os.environ)
    selected = affected.select(repo, affected.changed_files(root, base))
    tests = pending(repo, selected, ledger)
    if len(tests) < len(selected):
        print(f"runtests: {len(selected) - len(tests)} of {len(selected)} selected test files already green (ledger)", flush=True)
    n_tests = count_tests(root, tests)
    n = workers(n_tests)
    print(f"runtests: {len(tests)} test files, {n_tests} tests, {n} worker{'s' if n > 1 else ''} (change against {base[:12]})", flush=True)
    note = wide_note(root, n_tests)
    if note:
        print(note, flush=True)
    home = scratch.scratch_dir(os.environ, "tl-run-")
    try:
        env = isolated_env(home)
        parallel = pytest(root, env, "not serial and not quarantine", tests, n)
        serial = pytest(root, env, "serial and not quarantine", tests, 1)
        held = pytest(root, env, "quarantine", tests, 1)  # apart: a red one is said, never the run's verdict (tests/quarantine.txt)
        if held not in (0, NO_TESTS):
            print(f"runtests: quarantined tests are red (exit {held}); not blocking", flush=True)
        summary = testtimes_report.budget_warning(sorted(str(p) for p in home.glob("times-*.json")))
        if summary:
            print(summary, flush=True)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    record(repo, tests, ledger, [parallel, serial])
    return next((code for code in (parallel, serial) if code not in (0, NO_TESTS)), 0)


if __name__ == "__main__":
    sys.exit(main())
