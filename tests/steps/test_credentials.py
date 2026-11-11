"""The machine's Codex credential source (the whole environment minus the baseline scrub, the venv, a file login) and
the hardened Git environment of every factory Git view."""

from pathlib import Path
from typing import Literal

import pytest
from any_agent.procs import Worker
from git_porcelain import GitUnavailable, RealRepo
from stream_proc import OwnedProcess, ProcessObservation

from taskloop import composition
from taskloop.attempt import CredentialsUnavailable
from taskloop.composition import checkouts, codex_machine_credentials, hardened, worker_gone

BASE = {"PATH": "/usr/bin:/bin", "HOME": "/home/me"}
BAR = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "url.delegate-push-refused://.pushInsteadOf", "GIT_CONFIG_VALUE_0": ""}


class Machine:
    """Injected `which` and `exists`: records what was looked up, opens nothing."""

    def __init__(self, codex: str | None = "/usr/bin/codex", logins: tuple[str, ...] = ("/home/me/.codex/auth.json",)) -> None:
        self.codex, self.logins = codex, logins
        self.searched: list[str | None] = []
        self.checked: list[Path] = []

    def which(self, cmd: str, mode: int = 1, path: str | None = None) -> str | None:
        assert cmd == "codex"
        self.searched.append(path)
        return self.codex

    def exists(self, path: Path) -> bool:
        self.checked.append(path)
        return str(path) in self.logins


def credentials(environ: dict[str, str], machine: Machine | None = None) -> tuple[str, dict[str, str]]:
    machine = machine or Machine()
    return codex_machine_credentials(environ, machine.which, machine.exists)


@pytest.mark.parametrize(
    "name",
    [
        "CLAUDE_CODE_ENTRYPOINT",
        "ANTHROPIC_BASE_URL",
        "DELEGATE_LANE",
        "MCP_TIMEOUT",
        "OTEL_EXPORTER",
        "CODEX_COMPANION_SOCKET",
        "CLAUDECODE",
        "AI_AGENT",
        "API_TIMEOUT_MS",
        "BAGGAGE",
        "DISABLE_MICROCOMPACT",
        "DISABLE_AUTOUPDATER",
        "USE_LOCAL_OAUTH",
        "USE_STAGING_OAUTH",
        "aws_profile",
        "GH_HOST",
        "GITHUB_REPOSITORY",
        "SSH_AUTH_SOCK",
        "npm_token",
        "MY_SECRET_THING",
        "DB_PASSWORD",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "OPENAI_API_KEY",
        "someapikey",
        "S3_ACCESS_KEY_ID",
        "R2_ACCESSKEY",
        "SIGNING_PRIVATE_KEY",
        "GPG_PRIVATEKEY",
        "VIRTUAL_ENV_PROMPT",
        "PYTHONHOME",
        "__PYVENV_LAUNCHER__",
        "PYTHONEXECUTABLE",
    ],
)
def test_agent_session_credential_and_venv_variables_are_dropped(name: str) -> None:
    _exe, env = credentials({**BASE, name: "x"})
    assert name not in env and env == BASE | BAR


@pytest.mark.parametrize(
    "name",
    [
        "SHELL",
        "LOGNAME",
        "USER",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "CODEX_HOME",
        "claude_lowercase",  # the agent-session prefixes compare case-sensitively, as in the baseline rule
    ],
)
def test_the_rest_of_the_environment_passes(name: str) -> None:
    environ = {**BASE, name: "/home/me/.codex" if name == "CODEX_HOME" else "kept"}
    assert credentials(environ)[1] == environ | BAR


def test_the_virtualenv_and_its_bin_folder_are_stripped() -> None:
    environ = {"PATH": "/venv/bin:/usr/bin:/venv/bin/extra", "HOME": "/home/me", "VIRTUAL_ENV": "/venv"}
    machine = Machine()
    exe, env = credentials(environ, machine)
    assert exe == "/usr/bin/codex"
    assert env == {"PATH": "/usr/bin:/venv/bin/extra", "HOME": "/home/me"} | BAR
    assert machine.searched == [environ["PATH"]]


def test_codex_home_names_the_login_folder_and_a_relative_exe_becomes_absolute() -> None:
    machine = Machine(codex="bin/codex", logins=("/elsewhere/auth.json",))
    exe, _env = credentials({**BASE, "CODEX_HOME": "/elsewhere"}, machine)
    assert Path(exe).is_absolute() and exe.endswith("/bin/codex")
    assert machine.checked == [Path("/elsewhere/auth.json")]


@pytest.mark.parametrize(
    ("environ", "machine", "reason"),
    [
        ({"HOME": "/home/me"}, Machine(), "path"),
        (BASE, Machine(codex=None), "codex"),
        ({"PATH": "/usr/bin"}, Machine(), "home"),
        (BASE, Machine(logins=()), "auth"),
        ({**BASE, "CODEX_HOME": "/keyring-only"}, Machine(), "auth"),  # a keyring login has no auth.json: unsupported in v1
        ({**BASE, "GIT_CONFIG_COUNT": "two"}, Machine(), "git_config"),
        ({**BASE, "GIT_CONFIG_COUNT": "-1"}, Machine(), "git_config"),
    ],
)
def test_any_miss_is_unavailable_with_its_reason(environ: dict[str, str], machine: Machine, reason: str) -> None:
    with pytest.raises(CredentialsUnavailable) as raised:
        credentials(environ, machine)
    assert raised.value.reason == reason


def test_the_push_bar_is_appended_after_existing_git_config_entries() -> None:
    existing = {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "a.b",
        "GIT_CONFIG_VALUE_0": "1",
        "GIT_CONFIG_KEY_1": "c.d",
        "GIT_CONFIG_VALUE_1": "2",
    }
    _exe, env = credentials({**BASE, **existing})
    assert env == {
        **BASE,
        **existing,
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_2": "url.delegate-push-refused://.pushInsteadOf",
        "GIT_CONFIG_VALUE_2": "",
    }


def test_every_factory_git_view_runs_hardened_after_existing_git_config_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "1"}
    assert hardened(existing) == {
        "GIT_CONFIG_COUNT": "5",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": "/dev/null",
        "GIT_CONFIG_KEY_2": "core.fsmonitor",
        "GIT_CONFIG_VALUE_2": "false",
        "GIT_CONFIG_KEY_3": "commit.gpgSign",
        "GIT_CONFIG_VALUE_3": "false",
        "GIT_CONFIG_KEY_4": "maintenance.auto",
        "GIT_CONFIG_VALUE_4": "false",
    }
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.delenv("GIT_CEILING_DIRECTORIES", raising=False)
    view = checkouts(Path("/slots/s1"))
    assert isinstance(view, RealRepo) and view.extra_env == hardened({}) | {"GIT_CEILING_DIRECTORIES": "/slots"}
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "/home")  # the person's own ceiling stays, after the checkout's parent
    other = checkouts(Path("/slots/s1"))
    assert isinstance(other, RealRepo) and other.extra_env["GIT_CEILING_DIRECTORIES"] == "/slots:/home"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "two")
    with pytest.raises(GitUnavailable, match="GIT_CONFIG_COUNT"):
        checkouts(Path("/nowhere"))


@pytest.mark.parametrize(
    ("seen", "group", "expected"),
    [
        ("gone", False, True),
        ("different_process", False, True),
        ("gone", True, False),
        ("matching", False, False),
        ("unknown", False, False),
    ],
)
def test_the_worker_is_gone_only_with_its_process_and_its_group(
    monkeypatch: pytest.MonkeyPatch, seen: Literal["matching", "gone", "different_process", "unknown"], group: bool, expected: bool
) -> None:
    asked: list[object] = []
    monkeypatch.setattr(composition, "observe_owned", lambda identity: asked.append(identity) or ProcessObservation(seen))
    monkeypatch.setattr(composition, "group_alive", lambda pgid: asked.append(pgid) or group)
    assert worker_gone(Worker(pid=42, pgid=41, start="s", boot="b")) is expected
    assert asked[0] == OwnedProcess(42, 41, "s", "b")
