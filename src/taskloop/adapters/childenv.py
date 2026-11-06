"""The one builder of a child process's environment: a base mapping (an `Env` or the process's), cleaned, plus what the caller adds.
Never a copy of the whole process environment: a Python virtualenv of ours must not leak into a repo's gate (VIRTUAL_ENV,
2026-10-30), and a TL_* or TASK_LOOP_* name that is not in the registry (contracts/envvars.py) is not handed on."""
import shutil
import tempfile
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

import child_env

from taskloop.contracts.env import Env
from taskloop.contracts.envvars import PREFIXES, EnvVar, registered
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir, default_root

# The only names (besides the registered engine ones and LC_*) a tool, a check or git inherits. Anything else is declared by the repo's
# check (its `env`) or by the engine (`extra`), never picked up from whoever started the engine. A name is added below only when a real
# tool needed it (tests/checks/real/test_allowlist.py runs lifesim's and task-loop's own checks), with the reason.
ALLOWED = frozenset({
    "PATH",  # cleaned of the virtualenv's bin (child_env.without_venv)
    "HOME", "USER", "LANG", "TERM", "TMPDIR", "SHELL",
    # Added after the real-git tests and the real-tool checks (tests/checks/real/test_allowlist.py, the suite) went red without them:
    # git's identity where no user.name is configured (CI, a fresh HOME)
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    "UV",  # the uv that started the engine (uv run sets it): script_argv re-runs tl.py and release.py with it, not a PATH shim
    "UV_OFFLINE",  # release suite workers use prewarmed script environments, including their nested spawns
    "UV_CACHE_DIR",  # the same prewarmed cache despite each worker's isolated HOME
    "SSH_AUTH_SOCK", "GIT_SSH_COMMAND",  # a push over ssh finds its key in the agent / the owner's ssh command
})
ALLOWED_PREFIXES = (
    "LC_",
    "GIT_CONFIG_",  # git's own config injection: GIT_CONFIG_GLOBAL, GIT_CONFIG_NOSYSTEM, GIT_CONFIG_COUNT/KEY_n/VALUE_n (tests, CI)
)
ENGINE_PREFIXES = ("TL_", "TASK_LOOP_")


def allowed(name: str) -> bool:
    return name in ALLOWED or name.startswith(ALLOWED_PREFIXES) or (name.startswith(ENGINE_PREFIXES) and registered(name))


# The exec hand-overs: a process that replaces itself with a newer install passes these on (exec_env, the one writer); no child gets them.
HANDOVERS = frozenset({EnvVar.TL_REEXEC.value, EnvVar.TL_LOOP_STATE.value, EnvVar.TL_RELEASE_REEXEC.value})


def hooks_vars(env: Mapping[str, str], source: Mapping[str, str]) -> dict[str, str]:
    """core.hooksPath = tl's hooks dir, through git's own env config (GIT_CONFIG_COUNT/KEY_n/VALUE_n): a default for every child, not
    a lock (`git -c core.hooksPath=...` and --no-verify still beat it). A count the caller already set is extended, never replaced."""
    try:
        n = max(int(env.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        n = 0
    hooks = ConfigDir(default_root(Env(dict(source)))).hooks_dir()
    return {"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "core.hooksPath", f"GIT_CONFIG_VALUE_{n}": str(hooks)}


def tool_env(base: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """For a tool, a check or git: only the allowlisted names of `base` (PATH without the virtualenv, no exec hand-over), then `extra`
    over it."""
    env = {k: v for k, v in child_env.without_venv(base).items() if allowed(k) and k not in HANDOVERS}
    env.update(hooks_vars(env, base))
    env.update(extra or {})
    return env


CHECK_SECRETS = frozenset({"SSH_AUTH_SOCK", "GIT_SSH_COMMAND", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR",
                           "GIT_ASKPASS", "SSH_ASKPASS"})
CHECK_HOME_NAMES = frozenset({"HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "MISE_CONFIG_DIR"})


def check_caches(base: Mapping[str, str]) -> dict[str, str]:
    """Keep installed toolchains and warm caches reachable after HOME changes; these paths are not credential stores.

    Shared caches are intended for reuse, not a filesystem sandbox: environment isolation does not make them read-only.
    Only named mise directories are admitted, never arbitrary MISE_* settings (which can contain credentials).
    """
    home = Path(base.get("HOME") or "/nonexistent")
    cache = base.get("XDG_CACHE_HOME") or str(home / ".cache")
    data = base.get("XDG_DATA_HOME") or str(home / ".local/share")
    defaults = {"XDG_CACHE_HOME": cache, "UV_CACHE_DIR": str(Path(cache) / "uv"),
                "UV_PYTHON_INSTALL_DIR": str(Path(data) / "uv/python"), "MISE_CACHE_DIR": str(Path(cache) / "mise"),
                "MISE_DATA_DIR": str(Path(data) / "mise"), "MISE_STATE_DIR": str(home / ".local/state/mise")}
    return {k: base.get(k) or v for k, v in defaults.items()}


def check_env(base: Mapping[str, str], extra: Mapping[str, str] | None = None, *, home: str | None) -> dict[str, str]:
    """Strip check secrets in both modes; an explicit home isolates configuration from the owner's HOME."""
    env = {k: v for k, v in tool_env(base, extra).items() if k not in CHECK_SECRETS and not k.startswith("GIT_CREDENTIAL")}
    source = {**base, **{k: v for k, v in (extra or {}).items() if home is None or k != "HOME"}}
    env.update(check_caches(source))
    if home is None:
        env.update({k: v for k, v in source.items() if k in CHECK_HOME_NAMES or k.startswith("XDG_")})
    else:
        env.update(HOME=home, XDG_CONFIG_HOME=str(Path(home) / ".config"), XDG_DATA_HOME=str(Path(home) / ".local/share"),
                   XDG_STATE_HOME=str(Path(home) / ".local/state"), MISE_CONFIG_DIR=str(Path(home) / ".config/mise"))
    return env


def without_check_hooks(env: dict[str, str]) -> dict[str, str]:
    """Remove injected hooks from git's config sequence, preserving the order of all other entries."""
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    entries = [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(count)
               if env[f"GIT_CONFIG_KEY_{i}"].lower() != "core.hookspath"]
    out = {k: v for k, v in env.items() if not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    out["GIT_CONFIG_COUNT"] = str(len(entries))
    for i, (key, value) in enumerate(entries):
        out[f"GIT_CONFIG_KEY_{i}"], out[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return out


@contextmanager
def check_environment(base: Mapping[str, str], extra: Mapping[str, str] | None = None, *,
                      scratch_home: bool) -> Generator[dict[str, str]]:
    """Optionally use a private HOME, removed after the whole process group stops, including on exceptions."""
    if scratch_home:
        with tempfile.TemporaryDirectory(prefix="tl-check-home-") as home:
            yield without_check_hooks(check_env(base, extra, home=home))
    else:
        yield without_check_hooks(check_env(base, extra, home=None))


# Registered names that differ run to run without changing what a check does (paths of this run, ids of this process): not part of a
# result's identity. Every other registered name that reaches the child is.
PER_RUN = frozenset({EnvVar.TL_ARTIFACT_DIR, EnvVar.TL_ARTIFACT_STEP, EnvVar.TL_RUN_ID, EnvVar.TL_RUN_DIR, EnvVar.TL_ATTEMPT,
                     EnvVar.TL_WORKTREE, EnvVar.TL_BRANCH,
                     EnvVar.TL_REEXEC, EnvVar.TL_LOOP_STATE,
                     EnvVar.TL_RELEASE_REEXEC, EnvVar.TASK_LOOP_SLOT_BEAD, EnvVar.TASK_LOOP_ACTOR, EnvVar.TASK_LOOP_SESSION,
                     EnvVar.TASK_LOOP_LOOP_PID, EnvVar.TASK_LOOP_WORKER})


def reaching(env: Mapping[str, str]) -> dict[str, str]:
    """The registered engine names of `env` that reach a child (tool_env's filter) and are stable across runs: what a result may
    depend on, apart from the ambient system environment."""
    return {k: v for k, v in tool_env(env).items() if registered(k) and k not in PER_RUN and not k.startswith(PREFIXES)}


def run_env(*, run_id: str, run_dir: str | Path, attempt: int, artifact_dir: str | Path, worktree: str | Path,
            branch: str) -> dict[str, str]:
    """The six names every worker, check and gate command is told about its run (the cache key leaves them out: PER_RUN)."""
    return {EnvVar.TL_RUN_ID.value: run_id, EnvVar.TL_RUN_DIR.value: str(run_dir), EnvVar.TL_ATTEMPT.value: str(attempt),
            EnvVar.TL_ARTIFACT_DIR.value: str(artifact_dir), EnvVar.TL_WORKTREE.value: str(worktree), EnvVar.TL_BRANCH.value: branch}


def without(env: Mapping[str, str], *names: str) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in names}


GIT_PIN_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")  # the engine's own git is pinned; no child inherits a pin
KEEP = ("CLAUDE_CONFIG_DIR",)  # a worker on a custom Claude login must find it


WORKER_MARK = {"TASK_LOOP_WORKER": "1", "DELEGATE_DEPTH": "1"}  # what a child of the engine is told: it never delegates further


def child_env_of(env: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """`env` without what an agent session exports (CLAUDE_*, ANTHROPIC_*, DELEGATE_*, MCP_*, OTEL_*, CODEX_COMPANION*) and without
    TASK_LOOP_* and the git pins, but with CLAUDE_CONFIG_DIR. Credentials stay: delegate scrubs its workers itself (its own
    app-only scrub does the same for route.py); a worker never delegates further (DELEGATE_DEPTH=1)."""
    gone = (*child_env.APP_PREFIXES, "TASK_LOOP_")
    drop = (*child_env.APP_NAMES, *GIT_PIN_VARS)
    out = {k: v for k, v in child_env.without_venv(env).items() if k in KEEP or not (k.startswith(gone) or k in drop or k in HANDOVERS)}
    out.update(WORKER_MARK)
    out.update(hooks_vars(out, env))
    out.update(extra or {})
    return out


def script_argv(script: str | Path, env: Env) -> list[str]:
    """The argv that runs a script with a PEP 723 header (tl.py, dev/release.py): `uv run --script` installs its dependencies into
    a cached environment. `UV` of `env` is the uv that started this process, when one did."""
    return [env.get("UV") or shutil.which("uv") or "uv", "run", "--quiet", "--script", str(script)]


def current_env(env: Env, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of a worker started from `env` (child_env_of over the taken copy of the process's)."""
    return child_env_of(env.vars, extra)


def identity_env(who: Identity) -> dict[str, str]:
    """What a child needs to act as `who`: its actor and, when it has one, its session (read back by the child's `ident.identity`)."""
    out = {EnvVar.TASK_LOOP_ACTOR.value: who.actor}
    if who.session:
        out[EnvVar.TASK_LOOP_SESSION.value] = who.session
    return out


def exec_env(env: Env, handover: Mapping[EnvVar, str]) -> dict[str, str]:
    """The whole environment of `env` plus the exec hand-over (TL_REEXEC, TL_LOOP_STATE, TL_RELEASE_REEXEC): what a process that
    replaces itself with a newer install passes on. The one place those names are written."""
    return {**env.vars, **{var.value: value for var, value in handover.items()}}
