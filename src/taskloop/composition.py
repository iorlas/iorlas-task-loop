"""Construct the real Git, tracker and store boundaries for native command input."""

import os
import shutil
import sqlite3
import stat
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from any_agent import run
from any_agent.procs import Worker
from beads_client import Bd, Runner
from git_porcelain import GitUnavailable, RealRepo, Repo
from sqlite_store import Store
from stream_proc import OwnedProcess, group_alive, observe_owned, popen_registered

from taskloop.plan import Credentials, CredentialsUnavailable, PlanAttempts
from taskloop.plan_admit import Claim, PlanAdmission, Unclaim
from taskloop.plan_files import PlanFiles
from taskloop.plan_launch import Launcher
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import REGISTRATION_BUSY_MS, PlanStore
from taskloop.plan_types import Checkouts, FileEntry
from taskloop.plan_verifier import PlanVerifier
from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo
from taskloop.slots import Adopted, NotAdopted, adopt
from taskloop.task import TaskBinding, TaskInspection, TaskInspectionError, TaskScope
from taskloop.tracker import inspect_task

ACTOR = "taskloop"
# Baseline child_env.scrub defaults (731b7c76, skills/task-loop/_vendor/child_env), re-stated here, never imported.
APP_PREFIXES = ("CLAUDE_", "ANTHROPIC_", "DELEGATE_", "MCP_", "OTEL_", "CODEX_COMPANION")
APP_NAMES = frozenset(
    {
        "CLAUDECODE",
        "AI_AGENT",
        "API_TIMEOUT_MS",
        "BAGGAGE",
        "DISABLE_MICROCOMPACT",
        "DISABLE_AUTOUPDATER",
        "USE_LOCAL_OAUTH",
        "USE_STAGING_OAUTH",
    }
)
CREDENTIAL_PREFIXES = ("AWS_", "GH_", "GITHUB_")  # compared upper-cased, as are the names and markers below
CREDENTIAL_NAMES = frozenset({"SSH_AUTH_SOCK"})
CREDENTIAL_MARKERS = ("TOKEN", "SECRET", "PASSW", "CREDENTIAL", "API_KEY", "APIKEY", "ACCESS_KEY", "ACCESSKEY", "PRIVATE_KEY", "PRIVATEKEY")
# Not in the baseline scrub: the entry runs inside the factory's venv, and the agent must not inherit it.
VENV_NAMES = frozenset({"VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME", "__PYVENV_LAUNCHER__", "PYTHONEXECUTABLE"})
PUSH_REFUSED = "delegate-push-refused://"  # baseline delegate env.push_bar: no such remote helper, so git aborts any push
HARDENED = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"), ("commit.gpgSign", "false"), ("maintenance.auto", "false"))


class Which(Protocol):
    def __call__(self, cmd: str, mode: int = ..., path: str | None = ...) -> str | None: ...


def inspect_checkout(path: str) -> RepoInspection:
    """Resolve the native path once and request fresh shared-library observations."""
    try:
        expanded = Path(path).expanduser()
    except RuntimeError as error:
        raise UnsupportedCheckout(f"Cannot expand checkout path: {path}") from error
    checkout = expanded.resolve()
    return inspect_repo(RealRepo(checkout, memoize=False), checkout)


def inspect_tracker_task(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    """Bind the supplied logical backlog to the explicit tracker root, without discovery."""
    scope = TaskScope(backlog)
    if not tracker_root.strip():
        raise TaskInspectionError("invalid_binding", "An explicit nonempty tracker root is required")
    try:
        root = Path(tracker_root).expanduser().resolve()
        if not root.is_dir():
            raise TaskInspectionError("invalid_binding", f"Tracker root is not an available directory: {root}")
    except (RuntimeError, OSError) as error:
        raise TaskInspectionError("invalid_binding", f"Cannot resolve tracker root: {tracker_root}") from error
    binding = TaskBinding(scope, root)
    return inspect_task(binding, Bd(ACTOR, cwd=str(root)), task_id)


def _dropped(name: str) -> bool:
    upper = name.upper()
    return (
        name.startswith(APP_PREFIXES)
        or name in APP_NAMES
        or upper.startswith(CREDENTIAL_PREFIXES)
        or upper in CREDENTIAL_NAMES
        or any(marker in upper for marker in CREDENTIAL_MARKERS)
        or name in VENV_NAMES
    )


def codex_machine_credentials(
    environ: Mapping[str, str] = os.environ, which: Which = shutil.which, exists: Callable[[Path], bool] = Path.is_file
) -> tuple[str, dict[str, str]]:
    """The machine's Codex: an absolute `codex` on PATH and a file login (`auth.json`, checked by existence only).

    The agent gets the whole environment minus the baseline scrub and the active virtualenv. A keyring-only login and an
    API key in the environment are unsupported in v1. Any miss raises `CredentialsUnavailable` with a fixed reason.
    """
    search = environ.get("PATH")
    if not search:
        raise CredentialsUnavailable("path")
    found = which("codex", path=search)
    if not found:
        raise CredentialsUnavailable("codex")
    if environ.get("CODEX_HOME"):
        home = Path(environ["CODEX_HOME"])
    elif environ.get("HOME"):
        home = Path(environ["HOME"]) / ".codex"
    else:
        raise CredentialsUnavailable("home")
    if not exists(home / "auth.json"):
        raise CredentialsUnavailable("auth")
    env = {name: value for name, value in environ.items() if not _dropped(name)}
    venv = environ.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        venv_bin = os.path.join(venv, "bin")  # compared as text, like the baseline's exact PATH entry match
        env["PATH"] = os.pathsep.join(entry for entry in env["PATH"].split(os.pathsep) if entry != venv_bin)
    return str(Path(found).absolute()), env | push_bar(env)


def appended(env: Mapping[str, str], entries: Sequence[tuple[str, str]]) -> dict[str, str] | None:
    """Git env-config entries appended after any existing GIT_CONFIG_* ones (command-line scope, so no repository or
    user config file overrides them); None when the existing count is malformed."""
    count = env.get("GIT_CONFIG_COUNT") or "0"
    if not count.isascii() or not count.isdigit():
        return None
    n = int(count)
    added = {"GIT_CONFIG_COUNT": str(n + len(entries))}
    for i, (key, value) in enumerate(entries, n):
        added |= {f"GIT_CONFIG_KEY_{i}": key, f"GIT_CONFIG_VALUE_{i}": value}
    return added


def push_bar(env: Mapping[str, str]) -> dict[str, str]:
    """Baseline `push_bar`, re-stated: one more git env-config entry rewriting every push URL (the empty prefix matches all)
    to a scheme git cannot run, so a push by the agent fails whatever the credentials; fetch is untouched. A malformed
    count refuses."""
    bar = appended(env, [(f"url.{PUSH_REFUSED}.pushInsteadOf", "")])
    if bar is None:
        raise CredentialsUnavailable("git_config")
    return bar


def hardened(env: Mapping[str, str]) -> dict[str, str]:
    """Every factory Git call runs no hook (`--no-verify` skips only two: `prepare-commit-msg`, `post-commit`,
    `post-index-change` and `reference-transaction` would still run, from a hooks path the agent may have written), no
    fsmonitor program, no signing prompt and no automatic maintenance. This also stops `pre-push` for a later push from
    the same views; signed-commit repositories are unsupported. A malformed count is GitUnavailable (`git_config`)."""
    entries = appended(env, HARDENED)
    if entries is None:
        raise GitUnavailable("Malformed GIT_CONFIG_COUNT", hint="git_config")
    return entries


def ceiling(path: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """`GIT_CEILING_DIRECTORIES` with the checkout's parent first: when `<checkout>/.git` is gone, git_porcelain pins
    nothing and Git would discover an enclosing repository (a dotfiles repository at the home that holds the slots root);
    with the ceiling Git looks at the checkout itself and never above it. An ambient ceiling list is kept after it."""
    ambient = environ.get("GIT_CEILING_DIRECTORIES")
    return {"GIT_CEILING_DIRECTORIES": os.pathsep.join([str(path.parent), *([ambient] if ambient else [])])}


def worker_gone(worker: Worker) -> bool:
    """The registered agent process is gone (or its pid now names another process) and no process is left in its
    process group: the library's identity read and `killpg(pgid, 0)`. Unknown counts as alive. Not a stop proof for
    descendants that left the group (.4.4)."""
    seen = observe_owned(OwnedProcess(worker.pid, worker.pgid, worker.start, worker.boot)).kind
    return seen in ("gone", "different_process") and not group_alive(worker.pgid)


def checkouts(path: Path) -> Repo:
    """A fresh (unmemoized) real Git view from one checkout path, in the hardened Git environment, its discovery ceiling
    at that path: calls that run on a slot open their view from the slot itself."""
    return RealRepo(path, memoize=False, env=hardened(os.environ) | ceiling(path, os.environ))


class RealSlotFiles:
    """The slot file port over the real file system: `lstat` never follows a symlink, and a read opens only what `lstat`
    just saw as a regular file within the cap (`O_NOFOLLOW`, non-blocking), so a FIFO or symlink is never opened."""

    def lstat(self, path: Path) -> FileEntry | None:
        try:
            found = os.lstat(path)
        except (OSError, ValueError):  # ValueError: an embedded NUL; fails closed like a missing file
            return None
        mode = found.st_mode
        if stat.S_ISREG(mode):
            return FileEntry("file", found.st_size, bool(mode & 0o111))
        return FileEntry("dir" if stat.S_ISDIR(mode) else "link" if stat.S_ISLNK(mode) else "other", found.st_size, False)

    def read(self, path: Path, cap: int) -> bytes | None:
        entry = self.lstat(path)
        if entry is None or entry.kind != "file" or entry.size > cap:
            return None
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except (OSError, ValueError):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            data = stream.read(cap + 1)
        return data if len(data) <= cap else None

    def resolve(self, path: Path) -> Path | None:
        try:
            return path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None


def open_plan_attempts(database: Path, artifacts: Path, credentials: Credentials = codex_machine_credentials) -> PlanAttempts:
    """Real wiring: released run, per-thread shared writers on factory.db, wall-clock deadlines.

    The harness registration gate writes through its own store, whose connections wait at most REGISTRATION_BUSY_MS for the
    write lock; every other write keeps the library's 5 s.
    """
    store, gated = Store(SCHEMA), Store(SCHEMA)

    def bounded() -> sqlite3.Connection | None:
        con = gated.shared_rw(database)
        if con is not None:
            con.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")
        return con

    return PlanAttempts(
        PlanStore(lambda: store.shared_rw(database), store.begin_immediate),
        PlanFiles(artifacts),
        credentials,
        run,
        time.time,
        checkouts,
        RealSlotFiles(),
        gate=PlanStore(bounded, gated.begin_immediate),
    )


def open_plan_verifier(database: Path, store: Store) -> PlanVerifier:
    """Real wiring for on-demand verification: a shared writer of `store` (the caller closes it) on factory.db, real Git,
    wall clock."""
    writer = PlanStore(lambda: store.shared_rw(database), store.begin_immediate)
    return PlanVerifier(writer, checkouts, RealSlotFiles(), worker_gone, time.time)


def open_launcher(database: Path, artifacts: Path) -> Launcher:
    """Real wiring: the released registered start and owned-process observation, this interpreter, wall-clock deadlines.

    The database path is made absolute here: the entry refuses a relative one, after its registration would commit."""
    return Launcher(database.absolute(), PlanFiles(artifacts), time.time, popen_registered, observe_owned, sys.executable)


def adopt_slots(
    database: Path, checkout: Path, root: Path, count: int, repos: Checkouts = checkouts
) -> tuple[Adopted | NotAdopted, ...]:
    """Adopt worktrees a person already made with `git worktree add --detach <root>/<repo_id>/sN`; creates none."""
    store = Store(SCHEMA)
    try:
        repo = repos(checkout.expanduser().resolve())
        return adopt(lambda: store.shared_rw(database), store.begin_immediate, repo, root, count)
    finally:
        store.close_shared()


def tracker_claims(run: Runner | None = None) -> tuple[Claim, Unclaim]:
    """`Bd.claim` and the compensating `Bd.unclaim` fenced to this actor (never forced), bound per tracker root."""

    def bd(tracker_root: str) -> Bd:
        return Bd(ACTOR, cwd=str(Path(tracker_root).expanduser().resolve()), run=run)

    def claim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).claim(task_id)

    def unclaim(tracker_root: str, task_id: str) -> bool:
        return bd(tracker_root).unclaim(task_id, if_assignee=ACTOR)

    return claim, unclaim


def open_plan_admission(database: Path, artifacts: Path) -> PlanAdmission:
    """Real wiring: per-thread shared writers on factory.db, the tracker claim, the real Git boundary, wall-clock deadlines."""
    store = Store(SCHEMA)
    claim, unclaim = tracker_claims()
    return PlanAdmission(
        lambda: store.shared_rw(database),
        store.begin_immediate,
        PlanFiles(artifacts),
        inspect_tracker_task,
        checkouts,
        claim,
        unclaim,
        time.time,
    )
