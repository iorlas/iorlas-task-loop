"""The gate and the suite a release runs before it pushes: `just check`, then the whole unittest suite in parallel shards (or the
container's), skipped when this exact tree already passed this exact command."""
import contextlib
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ALL_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from types import FrameType

import stream_proc

from taskloop.adapters import landlock, procs
from taskloop.adapters.ident import config_dir
from taskloop.adapters.suiteout import Shard, failing_tests, failure_report, merge_outputs, ran_seconds
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, git, run, say

LONG = 3 * 3600.0  # a hang guard for a whole gate run
SHARD_WALL_S = 1200.0  # one shard's wall limit (the longest recorded shard is ~2.5 min at 3 workers: 8x); then its tree is stopped
SHARD_BUDGET_MB = 2048  # per shard: sets the shard count (RAM / budget), caps its address space (healthy ~430 MB) and is the refusal bar
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
    """What this host can run at once: min(cpu count, available RAM / SHARD_BUDGET_MB), never below 1 (unreadable RAM counts as enough)."""
    cpu = cpus if cpus is not None else (os.cpu_count() or 1)
    mem = mem_mb if mem_mb is not None else available_mb()
    return max(1, min(cpu, cpu if mem is None else mem // SHARD_BUDGET_MB))


def workers() -> int:
    """How many shards the suite runs in at once: TASK_LOOP_SUITE_WORKERS, else host_workers()."""
    n = os.environ.get("TASK_LOOP_SUITE_WORKERS")
    return max(1, int(n)) if n and n.isdigit() else host_workers()


def isolated_env(home: Path) -> dict[str, str]:
    """The environment of one shard: its own HOME, config dirs and temp dir, so shards do not share state under ~ or in /tmp.
    The real git config is copied in, since tests commit with the identity it holds."""
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("tmp", ".config"):
        (home / sub).mkdir(exist_ok=True)
    real = Path.home() / ".gitconfig"
    if real.is_file():
        (home / ".gitconfig").write_bytes(real.read_bytes())
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), TMPDIR=str(home / "tmp"))
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONPATH"):  # the tree under test sets its own PYTHONPATH
        env.pop(k, None)
    return env


def durations(work: Path) -> dict[str, float]:
    times: dict[str, float] = {}
    for f in work.glob("*.times"):
        with contextlib.suppress(OSError, ValueError):
            times.update(json.loads(f.read_text(encoding="utf-8")))
    return times


def suite_lock_path() -> Path:
    """One full suite per host: every host_suite run (a release's, dev/suite.py's, the container wrapper's fallback) takes this lock."""
    return config_dir() / "locks" / "suite-host.lock"


def run_shard(argv: list[str], cwd: str, env: dict[str, str], name: str, stop: threading.Event) -> Shard:
    """One shard through stream-proc: a session of its own, a wall limit, its whole tree stopped on the limit, on `stop`, or when this
    thread is unwound. A shard that outlived its limit is red, with what it printed."""
    out: list[str] = []
    res = stream_proc.run(argv, cwd=cwd, env=env, on_stdout=out.append, on_stderr=out.append, timeout=SHARD_WALL_S, stop=stop, grace=5.0)
    text = "".join(out)
    if res.timed_out:
        text += f"\n{name}: stopped after {res.secs:.0f}s ({res.timed_out}; limit {SHARD_WALL_S:.0f}s); its process tree was killed\n"
        return Shard(name, 124, text)
    return Shard(name, res.returncode if res.returncode is not None else 128 + (res.signal or 0), text)


def run_shards(shard: list[str], root: str, repo: Path, work: Path, todo: list[tuple[str, list[str]]]) -> list[Shard]:
    """`todo` shards at once, each in its own HOME; whatever ends this stops every shard tree first."""
    stop = threading.Event()
    text = Path(shard[-1]).read_text(encoding="utf-8")  # a tree older than these flags runs without them
    watch = ["--parent", str(os.getpid())] if "--parent" in text else []
    watch += ["--max-mb", str(SHARD_BUDGET_MB)] if "--max-mb" in text else []

    def go(name: str, ids: list[str]) -> Shard:
        f = work / (name + ".ids")
        f.write_text("\n".join(ids) + "\n", encoding="utf-8")
        argv = [*shard, "ids", str(f), "--root", root, "--times", str(work / (name + ".times")), *watch]
        return run_shard(argv, str(repo), isolated_env(work / name), name, stop)

    def term(signum: int, _frame: FrameType | None) -> None:
        stop.set()
        raise SystemExit(128 + signum)
    main = threading.current_thread() is threading.main_thread()
    old = signal.signal(signal.SIGTERM, term) if main else None
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
            try:
                futures = [pool.submit(go, n, i) for n, i in todo]
                while wait(futures, timeout=0.5, return_when=ALL_COMPLETED).not_done:  # a poll, so an interrupt lands at once
                    pass
                return [f.result() for f in futures]
            finally:
                stop.set()  # normal end too: a shard still running here is a stray
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def host_suite(tool_root: Path, repo: Path, record: bool = False) -> None:
    """The suite as N parallel shards, each its own process with its own HOME, then the tests of tests/shard.py SERIAL in one process.
    Holds the host-wide suite lock: a second full suite waits and says who holds it. `tool_root` holds the tests/shard.py that plans and
    runs them; `repo` is the tree under test. record=True also writes every test's seconds to tests/durations.json (what the splitter
    balances on) when the run is green."""
    holder = f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}: suite of {repo}"
    with landlock.os_lock(suite_lock_path(), holder, lambda who: say(f"waiting for the suite lock (held by {who})")):
        _host_suite(tool_root, repo, record)


def refuse_if_short(n: int, mem_mb: int | None) -> None:
    """One line and out when the free RAM is below the n shards' budgets together: no wait, no retry (the suite lock was won already)."""
    need = n * SHARD_BUDGET_MB
    if mem_mb is not None and mem_mb < need:
        raise Abort(f"not enough free memory for the suite: {mem_mb} MB available, {need} MB needed "
                    f"({n} shards x {SHARD_BUDGET_MB} MB); nothing run")


def _host_suite(tool_root: Path, repo: Path, record: bool) -> None:
    n = workers()
    refuse_if_short(n, available_mb())
    say(f"running the full suite in {n} shards, then the serial group")
    own = repo / "tests" / "shard.py"  # the tree under test runs with its own support code, not the installed checkout's
    shard = [sys.executable, str(own if own.is_file() else tool_root / "tests" / "shard.py")]
    root = str(repo / "tests")
    r = run([*shard, "plan", str(n), "--root", root], repo, check=False)
    try:
        plan = json.loads(r.stdout)
    except ValueError:
        out = (r.stdout + r.stderr).strip()
        raise red("could not plan the shards\n" + out, out.splitlines()) from None
    work = Path(tempfile.mkdtemp(prefix="tl-suite-"))
    began = time.monotonic()
    try:
        todo = [(f"shard{i}", ids) for i, ids in enumerate(plan["shards"], 1) if ids]
        parts = run_shards(shard, root, repo, work, todo)
        if plan["serial"]:
            parts += run_shards(shard, root, repo, work, [("serial", plan["serial"])])
        times = durations(work) if record else {}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    planned = sum(len(s) for s in plan["shards"]) + len(plan["serial"])
    out, green = merge_outputs(parts, planned, time.monotonic() - began)
    if green and record and times:
        (repo / "tests" / "durations.json").write_text(json.dumps({k: round(v, 3) for k, v in sorted(times.items())}, indent=0) + "\n",
                                                       encoding="utf-8")
        say(f"recorded {len(times)} test durations")
    say("shards: " + " ".join(f"{p.name}={ran_seconds(p.out) or 0:.0f}s" for p in parts))
    if not green:
        raise red(out, out.splitlines())
    say("suite green: " + " ".join(x for x in out.splitlines()[-3:] if x.strip()))


def container_suite(tool_root: Path, repo: Path) -> None:
    """The suite through dev/suite-docker.py (a Linux container's own disk; the host suite when docker is not reachable).
    TASK_LOOP_SUITE_HOST=1 runs it on the host. A fake repo (the tests') has no runner of its own: it takes the host runner."""
    if os.environ.get("TASK_LOOP_SUITE_HOST") or not (repo / "dev" / "suite.py").is_file():
        return host_suite(tool_root, repo)
    say("running the full suite in a container (dev/suite-docker.py)")
    ran = procs.capture([sys.executable, str(tool_root / "dev" / "suite-docker.py"), "--repo", str(repo)], None, None, LONG)
    out = ran.out + ran.err
    sys.stdout.write(out)
    if ran.exit:
        raise red(out, out.splitlines())


def gate_command() -> list[str]:
    return ["just", "check"] if shutil.which("just") else ["mise", "exec", "--", "just", "check"]


def gate(repo: Path) -> None:
    """The repo's own gate before the suite: `just check` (ruff, pyrefly, the structural rules test), whenever the repo has a justfile.
    `just` comes from PATH, else through mise; the config paths mise must trust are exported."""
    if not (repo / "justfile").is_file():  # a bare repo (the tests' fakes) has no gate of its own
        return
    cmd = gate_command()
    home = os.path.expanduser("~")
    env = dict(os.environ, MISE_TRUSTED_CONFIG_PATHS=os.pathsep.join([home + "/.config/mise", home + "/Workspaces"]))
    say("running the gate: " + " ".join(cmd))
    ran = procs.capture(cmd, str(repo), env, LONG)
    if ran.exit:
        raise Abort(f"the gate is red; nothing released (`just check` exit {ran.exit}):\n{(ran.out + ran.err).strip()[-3000:]}")
    say("gate green")


def run_checks(tool_root: Path, repo: Path) -> None:
    gate(repo)
    container_suite(tool_root, repo)


def verify(tool_root: Path, repo: Path, checks: Callable[[Path, Path], None] = run_checks) -> bool:
    """The gate and the suite on the tree at `repo`'s HEAD (nothing uncommitted). The same tree under the same command passed before:
    both are skipped, and the log says so (True). Only a green run is remembered; a red one raises and remembers nothing."""
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    command = " ".join(gate_command()) + " + " + ("host" if os.environ.get("TASK_LOOP_SUITE_HOST") else "container") + " suite"
    cache = SuiteCache(config_dir() / "releases" / "suite-green.json")
    if cache.hit(tree, command):
        say(f"suite cache hit: tree {tree[:12]} already passed `{command}`")
        return True
    checks(tool_root, repo)
    cache.record(tree, command, time.time())
    return False
