"""The gate and the suite a release runs before it pushes: `just check`, then the whole suite through pytest-xdist workers (or the
container's), skipped when this exact tree already passed this exact command."""
import contextlib
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import stream_proc

from taskloop.adapters import landlock
from taskloop.adapters.childenv import tool_env
from taskloop.adapters.ident import config_dir
from taskloop.adapters.suiteout import Part, failing_tests, failure_report, merge_outputs, ran_line
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, Shell, say
from taskloop.contracts import env as penv
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.paths import ConfigDir

LONG = 3 * 3600.0  # a hang guard for a whole gate run
STALE_TMP_S = 2 * LONG  # a tl-suite-* dir this old belongs to a suite that was killed without unwinding (SIGKILL): no live one runs so long
RUN_WALL_S = 1200.0  # one pytest run's wall limit (the whole parallel run takes under a minute here: 20x); then its tree is stopped
WORKER_BUDGET_MB = 2048  # per worker: sets the worker count (RAM / budget), caps its address space (healthy ~430 MB) and is the refusal bar
NO_TESTS = 5  # pytest's exit code for "no tests collected"
MEMINFO = Path("/proc/meminfo")
PROC_CGROUP = Path("/proc/self/cgroup")
CGROUP_ROOT = Path("/sys/fs/cgroup")


def save_output(out: str) -> Path:
    """The full suite output, in the config dir: a file inside the checkout would make the tree dirty and block the release."""
    d = config_dir() / "releases"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"suite-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.log"
    f.write_text(out, encoding="utf-8")
    return f


def red(out: str, lines: list[str]) -> Abort:
    log = save_output(out)
    return Abort("the suite is red; nothing released:\n{}\nfull output: {}".format(failure_report(out) or "\n".join(lines[-40:]), log),
                 log, failing_tests(out))


def cgroup_headroom_mb() -> int | None:
    """memory.max minus memory.current of this process's cgroup v2, MB; None when there is no numeric limit (v1, "max", missing or
    garbage files)."""
    try:
        line = next(ln for ln in PROC_CGROUP.read_text(encoding="utf-8").splitlines() if ln.startswith("0::"))
        d = CGROUP_ROOT / line[3:].strip().lstrip("/")
        limit = int((d / "memory.max").read_text(encoding="utf-8").strip())
        used = int((d / "memory.current").read_text(encoding="utf-8").strip())
    except (OSError, ValueError, StopIteration):
        return None
    return max(0, limit - used) // (1024 * 1024)


def available_mb() -> int | None:
    """RAM that can be used now, MB: MemAvailable on Linux, else the free pages sysconf reports (macOS: physical pages); on Linux capped
    by the cgroup headroom, because inside a container /proc/meminfo shows the HOST's memory, not the container's limit."""
    host = host_available_mb()
    cap = cgroup_headroom_mb()
    return host if cap is None else cap if host is None else min(host, cap)


def host_available_mb() -> int | None:
    try:
        for line in MEMINFO.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = next((os.sysconf(k) for k in ("SC_AVPHYS_PAGES", "SC_PHYS_PAGES") if k in os.sysconf_names), 0)
        return pages * page // (1024 * 1024) or None
    except (OSError, ValueError):
        return None


def host_workers(cpus: int | None = None, mem_mb: int | None = None) -> int:
    """What this host can run at once: min(cpu count, available RAM / WORKER_BUDGET_MB), never below 1 (unreadable RAM counts as enough)."""
    cpu = cpus if cpus is not None else (os.cpu_count() or 1)
    mem = mem_mb if mem_mb is not None else available_mb()
    return max(1, min(cpu, cpu if mem is None else mem // WORKER_BUDGET_MB))


def workers() -> int:
    """How many shards the suite runs in at once: TASK_LOOP_SUITE_WORKERS, else host_workers()."""
    n = penv.ambient(EnvVar.TASK_LOOP_SUITE_WORKERS)
    return max(1, int(n)) if n and n.isdigit() else host_workers()


def isolated_env(home: Path) -> dict[str, str]:
    """The environment of one pytest run: its own HOME, config dirs and temp dir, so runs do not share state under ~ or in /tmp (the xdist
    workers of a run each take one of their own, tests/conftest.py).
    The real git config is copied in, since tests commit with the identity it holds."""
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(exist_ok=True)
    real = Path.home() / ".gitconfig"
    if real.is_file():
        (home / ".gitconfig").write_bytes(real.read_bytes())
    env = tool_env(penv.snapshot().vars, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "TMPDIR": str(home / "tmp")})
    env[EnvVar.TL_WORKER_MB.value] = str(WORKER_BUDGET_MB)  # the address-space cap of each xdist worker (tests/conftest.py)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONPATH"):  # the tree under test sets its own PYTHONPATH
        env.pop(k, None)
    return env


def suite_lock_path() -> Path:
    """One full suite per host: every host_suite run (a release's, dev/suite.py's, the container wrapper's fallback) takes this lock."""
    return config_dir() / "locks" / "suite-host.lock"


def run_pytest(argv: list[str], cwd: str, env: dict[str, str], name: str, empty_ok: bool = False) -> Part:
    """One pytest run through stream-proc: a session of its own, a wall limit, its whole tree (the xdist workers) stopped on the limit
    or when this thread is unwound (an interrupt, SIGTERM). A run that outlived its limit is red, with what it printed. `empty_ok`: pytest's
    "no tests collected" (exit 5) is green (a tree without a serial group)."""
    out: list[str] = []
    res = stream_proc.run(argv, cwd=cwd, env=env, on_stdout=out.append, on_stderr=out.append, timeout=RUN_WALL_S, grace=5.0)
    text = "".join(out)
    if res.timed_out:
        text += f"\n{name}: stopped after {res.secs:.0f}s ({res.timed_out}; limit {RUN_WALL_S:.0f}s); its process tree was killed\n"
        return Part(name, 124, text)
    code = res.returncode if res.returncode is not None else 128 + (res.signal or 0)
    return Part(name, 0 if empty_ok and code == NO_TESTS else code, text)


def pytest_argv(tool_root: Path, *select: str) -> list[str]:
    """pytest from the venv `uv sync` made for `tool_root`'s pyproject (the tree under test may be a bare fake with none), over tests/."""
    return [str(tool_root / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *select, "tests"]


def run_parts(tool_root: Path, repo: Path, work: Path, n: int) -> list[Part]:
    """The parallel run (n xdist workers, each its own HOME), then the `serial` group alone in one process; SIGTERM unwinds into the
    run, which stops its tree first."""
    def term(signum: int, _frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)
    main = threading.current_thread() is threading.main_thread()
    old = signal.signal(signal.SIGTERM, term) if main else None
    try:
        spread = ["-n", str(n)] if n > 1 else []  # one worker is the run's own process
        parallel = run_pytest(pytest_argv(tool_root, *spread, "-m", "not serial"), str(repo),
                              isolated_env(work / "parallel"), "parallel")
        serial = run_pytest(pytest_argv(tool_root, "-m", "serial"), str(repo), isolated_env(work / "serial"), "serial", empty_ok=True)
        return [parallel, serial]
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def sweep_stale_tmp(now: float | None = None) -> None:
    """The tmp dirs of suites that never reached their `finally` (SIGKILL, power) go; a live suite's is far younger than STALE_TMP_S."""
    cut = (time.time() if now is None else now) - STALE_TMP_S
    for d in Path(tempfile.gettempdir()).glob("tl-suite-*"):
        with contextlib.suppress(OSError):
            if d.is_dir() and d.stat().st_mtime < cut:
                shutil.rmtree(d, ignore_errors=True)


def host_suite(tool_root: Path, repo: Path, sh: Shell) -> None:
    """The suite as N parallel pytest-xdist workers (each its own HOME), then the tests marked `serial` (tests/conftest.py SERIAL) in one
    process. Holds the host-wide suite lock: a second full suite waits and says who holds it. `tool_root` holds the pyproject (pytest and
    xdist) that runs them; `repo` is the tree under test."""
    holder = f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}: suite of {repo}"
    with landlock.os_lock(suite_lock_path(), holder, lambda who: say(f"waiting for the suite lock (held by {who})")):
        sweep_stale_tmp()
        _host_suite(tool_root, repo, sh)


def refuse_if_short(n: int, mem_mb: int | None) -> None:
    """One line and out when the free RAM is below the n workers' budgets together: no wait, no retry (the suite lock was won already)."""
    need = n * WORKER_BUDGET_MB
    if mem_mb is not None and mem_mb < need:
        raise Abort(f"not enough free memory for the suite: {mem_mb} MB available, {need} MB needed "
                    f"({n} workers x {WORKER_BUDGET_MB} MB); nothing run")


def _host_suite(tool_root: Path, repo: Path, sh: Shell) -> None:
    n = workers()
    refuse_if_short(n, available_mb())
    say(f"running the full suite in {n} workers, then the serial group")
    sh.run(["uv", "sync", "--frozen", "--quiet", "--project", str(tool_root)], tool_root)  # the dev group exactly as uv.lock records it
    work = Path(tempfile.mkdtemp(prefix="tl-suite-"))
    try:
        parts = run_parts(tool_root, repo, work, n)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out, green = merge_outputs(parts)
    say(" ".join(f"{p.name}: {ran_line(p.out)}" for p in parts))
    if not green:
        raise red(out, out.splitlines())
    say("suite green")


def container_suite(tool_root: Path, repo: Path, sh: Shell) -> None:
    """The suite through dev/suite-docker.py (a Linux container's own disk; the host suite when docker is not reachable).
    TASK_LOOP_SUITE_HOST=1 runs it on the host. A fake repo (the tests') has no runner of its own: it takes the host runner."""
    if penv.ambient(EnvVar.TASK_LOOP_SUITE_HOST) or not (repo / "dev" / "suite.py").is_file():
        return host_suite(tool_root, repo, sh)
    say("running the full suite in a container (dev/suite-docker.py)")
    ran = sh.run([sys.executable, str(tool_root / "dev" / "suite-docker.py"), "--repo", str(repo)], None, check=False, timeout_s=LONG)
    out = ran.stdout + ran.stderr
    sys.stdout.write(out)
    if ran.returncode:
        raise red(out, out.splitlines())


def gate_command() -> list[str]:
    return ["just", "check"] if shutil.which("just") else ["mise", "exec", "--", "just", "check"]


def gate(repo: Path, sh: Shell) -> None:
    """The repo's own gate before the suite: `just check` (ruff, pyrefly, the structural rules test), whenever the repo has a justfile.
    `just` comes from PATH, else through mise; the config paths mise must trust are exported."""
    if not (repo / "justfile").is_file():  # a bare repo (the tests' fakes) has no gate of its own
        return
    cmd = gate_command()
    home = os.path.expanduser("~")
    trusted = {"MISE_TRUSTED_CONFIG_PATHS": os.pathsep.join([home + "/.config/mise", home + "/Workspaces"])}
    say("running the gate: " + " ".join(cmd))
    ran = sh.run(cmd, repo, check=False, extra=trusted, timeout_s=LONG)
    if ran.returncode:
        raise Abort(f"the gate is red; nothing released (`just check` exit {ran.returncode}):\n{(ran.stdout + ran.stderr).strip()[-3000:]}")
    say("gate green")


def run_checks(tool_root: Path, repo: Path, sh: Shell) -> None:
    gate(repo, sh)
    container_suite(tool_root, repo, sh)


def verify(tool_root: Path, repo: Path, sh: Shell, checks: Callable[[Path, Path, Shell], None] = run_checks) -> bool:
    """The gate and the suite on the tree at `repo`'s HEAD (nothing uncommitted). The same tree under the same command passed before:
    both are skipped, and the log says so (True). Only a green run is remembered; a red one raises and remembers nothing."""
    tree = sh.git(repo, "rev-parse", "HEAD^{tree}")
    command = " ".join(gate_command()) + " + " + ("host" if penv.ambient(EnvVar.TASK_LOOP_SUITE_HOST) else "container") + " suite"
    cache = SuiteCache(ConfigDir(config_dir()))
    if cache.hit(tree, command):
        say(f"suite cache hit: tree {tree[:12]} already passed `{command}`")
        return True
    checks(tool_root, repo, sh)
    cache.record(tree, command, time.time())
    return False
