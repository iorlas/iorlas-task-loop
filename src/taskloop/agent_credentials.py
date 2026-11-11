"""The machine's Codex and the agent's scrubbed environment with the push bar. Wired by `composition`."""

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from taskloop.attempt import CredentialsUnavailable
from taskloop.git_views import appended

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
    return str(Path(found).absolute()), scrubbed(environ)


def scrubbed(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment minus the baseline scrub and the active virtualenv (its `bin` dropped from PATH), plus the push
    bar: what an agent and a checks attempt's commands get. No Codex lookup, so checks need no `codex`; it hides no file
    (Codex's login stays readable to code on the host). A malformed Git config count raises `CredentialsUnavailable`."""
    env = {name: value for name, value in environ.items() if not _dropped(name)}
    venv = environ.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        venv_bin = os.path.join(venv, "bin")  # compared as text, like the baseline's exact PATH entry match
        env["PATH"] = os.pathsep.join(entry for entry in env["PATH"].split(os.pathsep) if entry != venv_bin)
    return env | push_bar(env)


def push_bar(env: Mapping[str, str]) -> dict[str, str]:
    """Baseline `push_bar`, re-stated: one more git env-config entry rewriting every push URL (the empty prefix matches all)
    to a scheme git cannot run, so a push by the agent fails whatever the credentials; fetch is untouched. A malformed
    count refuses."""
    bar = appended(env, [(f"url.{PUSH_REFUSED}.pushInsteadOf", "")])
    if bar is None:
        raise CredentialsUnavailable("git_config")
    return bar
