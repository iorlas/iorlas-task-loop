"""Construct the real Git, tracker and store boundaries for native command input."""

import os
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from any_agent import run
from beads_client import Bd, Runner
from git_porcelain import RealRepo
from sqlite_store import Store
from stream_proc import observe_owned, popen_registered

from taskloop.plan import Credentials, CredentialsUnavailable, PlanAttempts
from taskloop.plan_admit import Claim, PlanAdmission, Unclaim
from taskloop.plan_files import PlanFiles
from taskloop.plan_launch import Launcher
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import REGISTRATION_BUSY_MS, PlanStore
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


def push_bar(env: Mapping[str, str]) -> dict[str, str]:
    """Baseline `push_bar`, re-stated: one more git env-config entry rewriting every push URL (the empty prefix matches all)
    to a scheme git cannot run, so an approved out-of-sandbox push fails whatever the credentials; fetch is untouched.
    Existing GIT_CONFIG_* entries are kept and the bar is appended after them; a malformed count refuses."""
    count = env.get("GIT_CONFIG_COUNT") or "0"
    if not count.isascii() or not count.isdigit():
        raise CredentialsUnavailable("git_config")
    n = int(count)
    return {"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": f"url.{PUSH_REFUSED}.pushInsteadOf", f"GIT_CONFIG_VALUE_{n}": ""}


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
        gate=PlanStore(bounded, gated.begin_immediate),
    )


def open_launcher(database: Path, artifacts: Path) -> Launcher:
    """Real wiring: the released registered start and owned-process observation, this interpreter, wall-clock deadlines.

    The database path is made absolute here: the entry refuses a relative one, after its registration would commit."""
    return Launcher(database.absolute(), PlanFiles(artifacts), time.time, popen_registered, observe_owned, sys.executable)


def adopt_slots(database: Path, checkout: Path, root: Path, count: int) -> tuple[Adopted | NotAdopted, ...]:
    """Adopt worktrees a person already made with `git worktree add --detach <root>/<repo_id>/sN`; creates none."""
    store = Store(SCHEMA)
    try:
        repo = RealRepo(checkout.expanduser().resolve(), memoize=False)
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
        lambda checkout: RealRepo(checkout, memoize=False),
        claim,
        unclaim,
        time.time,
    )
