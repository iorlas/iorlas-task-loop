"""The selected local agent executable and scrubbed environment with the push bar. Wired by `composition`."""

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from taskloop.agents.launch import CredentialReason, CredentialsUnavailable
from taskloop.harness_choice import HarnessKind

# The base environment of an agent and of every checks command: an allow-list. Everything else (DATABASE_URL, KUBECONFIG, GIT_DIR,
# BASH_ENV, LD_PRELOAD, PYTHONPATH, GIT_CONFIG_*, tokens, cloud and registry settings) is dropped, whatever its name. A variable a
# project needs is named by the person in the factory's own environment: `TASKLOOP_ENV_PASS=NAME,NAME` (owner-approved by being
# set there). Compared exactly; lower-case proxy names are the usual ones.
BASE_NAMES = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TZ", "TMPDIR", "CODEX_HOME",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "CURL_CA_BUNDLE", "UV_NATIVE_TLS",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    }
)
PASS_NAMES = "TASKLOOP_ENV_PASS"
PUSH_REFUSED = "delegate-push-refused://"  # baseline delegate env.push_bar: no such remote helper, so git aborts any push


class Which(Protocol):
    def __call__(self, cmd: str, mode: int = ..., path: str | None = ...) -> str | None: ...


def _kept(name: str, extra: frozenset[str]) -> bool:
    return name in BASE_NAMES or name.startswith(("LC_", "MISE_")) or name in extra  # MISE_*: a shim PATH needs its trusted paths


def codex_machine_credentials(
    environ: Mapping[str, str] = os.environ, which: Which = shutil.which, exists: Callable[[Path], bool] = Path.is_file
) -> tuple[str, dict[str, str]]:
    """The machine's Codex: an absolute `codex` on PATH and a file login (`auth.json`, checked by existence only).

    The agent gets the allow-listed environment (`scrubbed`). A keyring-only login and an
    API key in the environment are unsupported in v1. Any miss raises `CredentialsUnavailable` with a fixed reason.
    """
    search = environ.get("PATH")
    if not search:
        raise CredentialsUnavailable(CredentialReason.PATH, "The agent executable needs PATH.")
    found = which("codex", path=search)
    if not found:
        raise CredentialsUnavailable(CredentialReason.EXECUTABLE, "Codex is not available on PATH.")
    if environ.get("CODEX_HOME"):
        home = Path(environ["CODEX_HOME"])
    elif environ.get("HOME"):
        home = Path(environ["HOME"]) / ".codex"
    else:
        raise CredentialsUnavailable(CredentialReason.HOME, "Codex needs HOME or CODEX_HOME for its file login.")
    if not exists(home / "auth.json"):
        raise CredentialsUnavailable(CredentialReason.AUTH, "Codex needs its local file login (auth.json).")
    return str(Path(found).absolute()), scrubbed(environ)


def scrubbed(environ: Mapping[str, str]) -> dict[str, str]:
    """The allow-listed environment (`BASE_NAMES`, `LC_*`, the names in `TASKLOOP_ENV_PASS`) with the active virtualenv's
    `bin` dropped from PATH, plus the push bar: what an agent and a checks attempt's commands get. No Codex lookup, so
    checks need no `codex`; it hides no file (Codex's login stays readable to code on the host)."""
    extra = frozenset(name.strip() for name in environ.get(PASS_NAMES, "").split(",") if name.strip())
    env = {name: value for name, value in environ.items() if _kept(name, extra)}
    venv = environ.get("VIRTUAL_ENV")
    if venv and "PATH" in env:
        venv_bin = os.path.join(venv, "bin")  # compared as text, like the baseline's exact PATH entry match
        env["PATH"] = os.pathsep.join(entry for entry in env["PATH"].split(os.pathsep) if entry != venv_bin)
    return env | push_bar()


def push_bar() -> dict[str, str]:
    """One git env-config entry rewriting every push URL (the empty prefix matches all) to a scheme git cannot run, so a push
    by the agent fails whatever the credentials; fetch is untouched. The environment's own `GIT_CONFIG_*` is never passed on."""
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{PUSH_REFUSED}.pushInsteadOf", "GIT_CONFIG_VALUE_0": ""}


def machine_credentials(
    harness: HarnessKind, environ: Mapping[str, str] = os.environ, which: Which = shutil.which,
    exists: Callable[[Path], bool] = Path.is_file,
) -> tuple[str, dict[str, str]]:
    """Selected local executable; Claude uses its subscription login, OpenCode its local configuration."""
    if harness is HarnessKind.CODEX:
        return codex_machine_credentials(environ, which, exists)
    search = environ.get("PATH")
    if not search:
        raise CredentialsUnavailable(CredentialReason.PATH, "The agent executable needs PATH.")
    found = which(harness.value, path=search)
    if not found:
        raise CredentialsUnavailable(CredentialReason.EXECUTABLE, f"The selected agent executable ({harness.value}) is not on PATH.")
    return str(Path(found).absolute()), scrubbed(environ)
