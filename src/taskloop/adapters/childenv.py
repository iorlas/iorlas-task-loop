"""The one builder of a child process's environment: a base mapping (an `Env` or the process's), cleaned, plus what the caller adds.
Never a copy of the whole process environment: a Python virtualenv of ours must not leak into a repo's gate (VIRTUAL_ENV,
2026-10-30), and a TL_* or TASK_LOOP_* name that is not in the registry (contracts/envvars.py) is not handed on."""
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

import child_env

from taskloop.contracts import env as penv
from taskloop.contracts.envvars import PREFIXES, EnvVar, registered

VENV_VARS = ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONHOME", "__PYVENV_LAUNCHER__", "PYTHONEXECUTABLE")
ENGINE_PREFIXES = ("TL_", "TASK_LOOP_")


def without_venv(env: Mapping[str, str]) -> dict[str, str]:
    """`env` without the active virtualenv: its variables, and its bin folder in PATH."""
    out = {k: v for k, v in env.items() if k not in VENV_VARS}
    venv = env.get("VIRTUAL_ENV")
    if venv and "PATH" in out:
        bin_dir = os.path.join(venv, "bin")
        out["PATH"] = os.pathsep.join(p for p in out["PATH"].split(os.pathsep) if p != bin_dir)
    return out


def tool_env(base: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """For a tool, a check or git: `base` without the virtualenv and without unregistered engine names, then `extra` over it."""
    env = {k: v for k, v in without_venv(base).items() if not k.startswith(ENGINE_PREFIXES) or registered(k)}
    env.update(extra or {})
    return env


# Registered names that differ run to run without changing what a check does (paths of this run, ids of this process): not part of a
# result's identity. Every other registered name that reaches the child is.
PER_RUN = frozenset({EnvVar.TL_ARTIFACTS, EnvVar.TL_ARTIFACT_STEP, EnvVar.TL_BOX_CWD, EnvVar.TL_REEXEC, EnvVar.TL_LOOP_STATE,
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


def child_env_of(env: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """`env` without what an agent session exports (CLAUDE_*, ANTHROPIC_*, DELEGATE_*, MCP_*, OTEL_*, CODEX_COMPANION*) and without
    TASK_LOOP_* and the git pins, but with CLAUDE_CONFIG_DIR. Credentials stay: delegate scrubs its workers itself (its own
    app-only scrub does the same for route.py); a worker never delegates further (DELEGATE_DEPTH=1)."""
    gone = (*child_env.APP_PREFIXES, "TASK_LOOP_")
    drop = (*child_env.APP_NAMES, *GIT_PIN_VARS)
    out = {k: v for k, v in without_venv(env).items() if k in KEEP or not (k.startswith(gone) or k in drop)}
    out.update({"TASK_LOOP_WORKER": "1", "DELEGATE_DEPTH": "1"})
    out.update(extra or {})
    return out


def script_argv(script: str | Path) -> list[str]:
    """The argv that runs a script with a PEP 723 header (tl.py, dev/release.py): `uv run --script` installs its dependencies into
    a cached environment. `UV` is the uv that started this process, when one did."""
    return [penv.ambient("UV") or shutil.which("uv") or "uv", "run", "--quiet", "--script", str(script)]


def current_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    return child_env_of(penv.snapshot().vars, extra)
