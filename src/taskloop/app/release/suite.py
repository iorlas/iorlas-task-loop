"""The gate and the suite a release runs before it pushes: `just check`, then the whole unittest suite in parallel shards (or the
container's), skipped when this exact tree already passed this exact command."""
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taskloop.adapters import procs
from taskloop.adapters.ident import config_dir
from taskloop.adapters.suiteout import Shard, failing_tests, failure_report, merge_outputs, ran_seconds
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, git, run, say

LONG = 3 * 3600.0  # a hang guard for a whole gate or suite run


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


def workers() -> int:
    """How many shards the suite runs in at once: TASK_LOOP_SUITE_WORKERS, else max(2, cpu count - 2)."""
    n = os.environ.get("TASK_LOOP_SUITE_WORKERS")
    return max(1, int(n)) if n and n.isdigit() else max(2, (os.cpu_count() or 1) - 2)


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
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONPATH"):  # PYTHONPATH: the tree under test sets its own (tests/support/paths.py)
        env.pop(k, None)
    return env


def durations(work: Path) -> dict[str, float]:
    times: dict[str, float] = {}
    for f in work.glob("*.times"):
        with contextlib.suppress(OSError, ValueError):
            times.update(json.loads(f.read_text(encoding="utf-8")))
    return times


def host_suite(tool_root: Path, repo: Path, record: bool = False) -> None:
    """The suite as N parallel shards, each its own process with its own HOME, then the tests of tests/shard.py SERIAL in one process.
    `tool_root` holds the tests/shard.py that plans and runs them; `repo` is the tree under test. record=True also writes every test's
    seconds to tests/durations.json (what the splitter balances on) when the run is green."""
    n = workers()
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

    def go(name: str, ids: list[str]) -> Shard:
        f = work / (name + ".ids")
        f.write_text("\n".join(ids) + "\n", encoding="utf-8")
        ran = procs.capture([*shard, "ids", str(f), "--root", root, "--times", str(work / (name + ".times"))], str(repo),
                            isolated_env(work / name), LONG)
        return Shard(name, ran.exit, ran.out + ran.err)
    try:
        todo = [(f"shard{i}", ids) for i, ids in enumerate(plan["shards"], 1) if ids]
        with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
            parts = list(pool.map(go, [n for n, _ in todo], [i for _, i in todo]))
        if plan["serial"]:
            parts.append(go("serial", plan["serial"]))
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
