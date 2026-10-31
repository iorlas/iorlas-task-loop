"""The one builder of a child process's environment: a base mapping (an `Env` or the process's), cleaned, plus what the caller adds.
Never a copy of the whole process environment: a Python virtualenv of ours must not leak into a repo's gate (VIRTUAL_ENV,
2026-10-30), and a TL_* or TASK_LOOP_* name that is not in the registry (contracts/envvars.py) is not handed on."""
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

import child_env

from taskloop.contracts.env import Env
from taskloop.contracts.envvars import PREFIXES, EnvVar, registered
from taskloop.contracts.identity import Identity

VENV_VARS = ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME", "__PYVENV_LAUNCHER__", "PYTHONEXECUTABLE")


def without_venv(env: Mapping[str, str]) -> dict[str, str]:
    """`env` without the active virtualenv: its variables, and its bin folder in PATH."""
    out = {k: v for k, v in env.items() if k not in VENV_VARS}
    venv = env.get("VIRTUAL_ENV")
    if venv and "PATH" in out:
        bin_dir = os.path.join(venv, "bin")
        out["PATH"] = os.pathsep.join(p for p in out["PATH"].split(os.pathsep) if p != bin_dir)
    return out


# The only names (besides the registered engine ones and LC_*) a tool, a check or git inherits. Anything else is declared by the repo's
# check (its `env`) or by the engine (`extra`), never picked up from whoever started the engine. A name is added below only when a real
# tool needed it (tests/checks/real/test_allowlist.py runs lifesim's and task-loop's own checks), with the reason.
ALLOWED = frozenset({
    "PATH",  # cleaned of the virtualenv's bin (without_venv)
    "HOME", "USER", "LANG", "TERM", "TMPDIR", "SHELL",
    # Added after the real-git tests and the real-tool checks (tests/checks/real/test_allowlist.py, the suite) went red without them:
    # git's identity where no user.name is configured (CI, a fresh HOME)
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    "UV",  # the uv that started the engine (uv run sets it): script_argv re-runs tl.py and release.py with it, not a PATH shim
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


def tool_env(base: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """For a tool, a check or git: only the allowlisted names of `base` (PATH without the virtualenv, no exec hand-over), then `extra`
    over it."""
    env = {k: v for k, v in without_venv(base).items() if allowed(k) and k not in HANDOVERS}
    env.update(extra or {})
    return env


# Registered names that differ run to run without changing what a check does (paths of this run, ids of this process): not part of a
# result's identity. Every other registered name that reaches the child is.
PER_RUN = frozenset({EnvVar.TL_ARTIFACTS, EnvVar.TL_ARTIFACT_STEP, EnvVar.TL_RUN_ID,
                     EnvVar.TL_BOX_CWD, EnvVar.TL_REEXEC, EnvVar.TL_LOOP_STATE,
                     EnvVar.TL_RELEASE_REEXEC, EnvVar.TASK_LOOP_SLOT_BEAD, EnvVar.TASK_LOOP_ACTOR, EnvVar.TASK_LOOP_SESSION,
                     EnvVar.TASK_LOOP_LOOP_PID, EnvVar.TASK_LOOP_WORKER})


def reaching(env: Mapping[str, str]) -> dict[str, str]:
    """The registered engine names of `env` that reach a child (tool_env's filter) and are stable across runs: what a result may
    depend on, apart from the ambient system environment."""
    return {k: v for k, v in tool_env(env).items() if registered(k) and k not in PER_RUN and not k.startswith(PREFIXES)}


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
    out = {k: v for k, v in without_venv(env).items() if k in KEEP or not (k.startswith(gone) or k in drop or k in HANDOVERS)}
    out.update(WORKER_MARK)
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
