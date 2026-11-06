"""`just test`: run the tests the change can break (dev/affected.py picks them), nothing else. Exit 0 green, pytest's code otherwise.

    python3 dev/runtests.py

Workers: min(cpus, free RAM / 2 GB, ceil(tests / 150), 4). A selection of 150 tests or fewer runs in this one pytest process, no xdist.
Isolation: the run has its own HOME, config and temp dirs (the real git identity is copied in); xdist workers take one each on top
(tests/conftest.py). The tests marked `serial` run alone, after the parallel ones, and only those the selection holds.
Whole-suite runs are `just test-full`, started by a person; this script has no such mode. Standard library only.
"""
import ast
import math
import os
import shutil
import signal
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "skills" / "task-loop" / "_vendor"))  # the vendored shelf packages
import affected
import stream_proc

CHUNK = 150          # tests per worker: a worker costs ~2 s to start and a few hundred MB, so a smaller share is not worth one
MAX_WORKERS = 4      # the box also runs the implementer workers; the tests must not starve them
WORKER_MB = 2048     # RAM budget of one worker
WALL_S = 3600.0      # a hang guard for one pytest run (a wide selection takes 15 min in 4 workers); its process tree is killed
NO_TESTS = 5         # pytest's exit code for "no tests collected" (a selection without a serial test)
DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONPATH")


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


def workers(n_tests, cpus=None, mem_mb=None):
    """How many pytest workers this selection earns on this host (1: no xdist)."""
    cpu = cpus if cpus is not None else (os.cpu_count() or 1)
    ram = mem_mb if mem_mb is not None else total_mb()
    return max(1, min(cpu, cpu if ram is None else ram // WORKER_MB, math.ceil(n_tests / CHUNK), MAX_WORKERS))


def isolated_env(home):
    """The environment of the run: its own HOME, config and temp dirs; the real git config copied in, since tests commit with it."""
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    real = Path.home() / ".gitconfig"
    if real.is_file():
        (home / ".gitconfig").write_bytes(real.read_bytes())
    # GIT_CONFIG_*: a release's core.hooksPath would fire tl's pre-push judge in the tests' repos
    env = {k: v for k, v in os.environ.items() if k not in DROP and not k.startswith("GIT_CONFIG_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), TMPDIR=str(home / "tmp"), TL_WORKER_MB=str(WORKER_MB))
    return env


def pytest(root, env, mark, tests, n):
    """One pytest run in a session of its own; the wall limit, an interrupt or SIGTERM stop it with its workers (stream_proc). Exit code."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *(["-n", str(n)] if n > 1 else []), "-m", mark, *tests]

    def term(signum, _frame):
        raise SystemExit(128 + signum)
    old = signal.signal(signal.SIGTERM, term)
    try:
        res = stream_proc.run(argv, cwd=root, env=env, timeout=WALL_S, on_stdout=lambda t: print(t, end="", flush=True),
                              on_stderr=lambda t: print(t, end="", file=sys.stderr, flush=True))
    finally:
        signal.signal(signal.SIGTERM, old)
    if res.timed_out:
        print(f"runtests: stopped after {WALL_S:.0f} s; its process tree was killed", file=sys.stderr)
        return 124
    return res.returncode if res.returncode is not None else 128 + (res.signal or 0)


def main():
    root = Path(__file__).resolve().parent.parent
    base = affected.base_of(root)
    tests = affected.select(affected.Repo(root), affected.changed_files(root, base))
    n_tests = count_tests(root, tests)
    n = workers(n_tests)
    print(f"runtests: {len(tests)} test files, {n_tests} tests, {n} worker{'s' if n > 1 else ''} (change against {base[:12]})", flush=True)
    home = Path(tempfile.mkdtemp(prefix="tl-run-"))
    try:
        env = isolated_env(home)
        parallel = pytest(root, env, "not serial", tests, n)
        serial = pytest(root, env, "serial", tests, 1)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return next((code for code in (parallel, serial) if code not in (0, NO_TESTS)), 0)


if __name__ == "__main__":
    sys.exit(main())
