"""The one builder of a child process's environment: a base mapping (an `Env` or the process's), cleaned, plus what the caller adds.
Never a copy of the whole process environment: a Python virtualenv of ours must not leak into a repo's gate (VIRTUAL_ENV,
2026-10-30), and a TL_* or TASK_LOOP_* name that is not in the registry (contracts/envvars.py) is not handed on."""
import os
from collections.abc import Mapping

from taskloop.contracts.envvars import registered

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


def without(env: Mapping[str, str], *names: str) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in names}
