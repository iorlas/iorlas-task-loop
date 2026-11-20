"""The machine's Codex credential source (the whole environment minus the baseline scrub, the venv, a file login) and
the hardened Git environment of every factory Git view."""

from pathlib import Path
from typing import Literal

import pytest
from any_agent.procs import Worker
from git_porcelain import GitUnavailable, RealRepo
from stream_proc import OwnedProcess, ProcessObservation

from taskloop import owned_processes
from taskloop.agent_credentials import codex_machine_credentials, scrubbed
from taskloop.agents.launch import CredentialsUnavailable
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.git_views import GitViews, hardened
from taskloop.owned_processes import worker_gone

VIEWS = GitViews(DEFAULT_GIT_READ_SECONDS)

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


DROPPED = [
    "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_BASE_URL", "CLAUDECODE", "AWS_PROFILE", "GH_HOST", "SSH_AUTH_SOCK", "NPM_TOKEN",
    "AUTHORIZATION", "BASH_ENV", "CI_JOB_JWT", "DATABASE_URL", "DOCKER_AUTH_CONFIG", "GIT_ASKPASS", "GIT_CONFIG_GLOBAL", "GIT_DIR",
    "GIT_SSH_COMMAND", "GIT_WORK_TREE", "GPG_AGENT_INFO", "KUBECONFIG", "LD_PRELOAD", "NETRC", "NPM_CONFIG__AUTH", "OPENAI_ORG_ID",
    "PGPASSFILE", "PYTHONPATH", "REDIS_URL", "SENTRY_DSN", "SLACK_WEBHOOK_URL", "SSH_AGENT_PID", "STRIPE_KEY", "UV_INDEX_URL",
    "GIT_CONFIG_KEY_3", "VIRTUAL_ENV_PROMPT", "PYTHONHOME", "claude_lowercase",
]


@pytest.mark.parametrize("name", DROPPED)
def test_only_the_allow_list_reaches_an_agent_and_the_checks(name: str) -> None:
    _exe, env = credentials({**BASE, name: "x"})
    assert name not in env and env == BASE | BAR
    assert scrubbed({**BASE, name: "x"}) == BASE | BAR


@pytest.mark.parametrize(
    "name", ["SHELL", "LOGNAME", "USER", "TERM", "TZ", "TMPDIR", "LANG", "LC_ALL", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "CODEX_HOME"]
)
def test_the_base_names_pass(name: str) -> None:
    environ = {**BASE, name: "/home/me/.codex" if name == "CODEX_HOME" else "kept"}
    assert credentials(environ)[1] == environ | BAR


def test_the_person_extends_the_list_by_name_in_the_factorys_own_environment() -> None:
    environ = {**BASE, "TASKLOOP_ENV_PASS": "UV_INDEX_URL, REDIS_URL", "UV_INDEX_URL": "u", "REDIS_URL": "r", "KUBECONFIG": "k"}
    assert scrubbed(environ) == BASE | {"UV_INDEX_URL": "u", "REDIS_URL": "r"} | BAR


def test_codex_home_names_the_login_folder_and_a_relative_exe_becomes_absolute() -> None:
    machine = Machine(codex="bin/codex", logins=("/elsewhere/auth.json",))
    exe, _env = credentials({**BASE, "CODEX_HOME": "/elsewhere"}, machine)
    assert Path(exe).is_absolute() and exe.endswith("/bin/codex")
    assert machine.checked == [Path("/elsewhere/auth.json")]


@pytest.mark.parametrize(
    ("environ", "machine", "reason"),
    [
        ({"HOME": "/home/me"}, Machine(), "path"),
        (BASE, Machine(codex=None), "executable"),
        ({"PATH": "/usr/bin"}, Machine(), "home"),
        (BASE, Machine(logins=()), "auth"),
        ({**BASE, "CODEX_HOME": "/keyring-only"}, Machine(), "auth"),  # a keyring login has no auth.json: unsupported in v1
    ],
)
def test_any_miss_is_unavailable_with_its_reason(environ: dict[str, str], machine: Machine, reason: str) -> None:
    with pytest.raises(CredentialsUnavailable) as raised:
        credentials(environ, machine)
    assert raised.value.reason == reason


def test_the_checks_environment_is_the_same_scrub_without_any_codex_lookup() -> None:
    """A checks attempt needs no `codex` on PATH and no login file; it gets exactly what the agent's credentials give."""
    environ = {**BASE, "PATH": "/venv/bin:/usr/bin", "VIRTUAL_ENV": "/venv", "GH_TOKEN": "t", "CODEX_HOME": "/c", "CLAUDECODE": "1"}
    assert scrubbed(environ) == credentials(environ, Machine(logins=("/c/auth.json",)))[1]
    assert scrubbed(environ) == {"PATH": "/usr/bin", "HOME": "/home/me", "CODEX_HOME": "/c"} | BAR


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
    view = VIEWS.checkouts(Path("/slots/s1"))
    assert isinstance(view, RealRepo) and view.extra_env == hardened({}) | {"GIT_CEILING_DIRECTORIES": "/slots"}
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", "/home")  # the person's own ceiling stays, after the checkout's parent
    other = VIEWS.checkouts(Path("/slots/s1"))
    assert isinstance(other, RealRepo) and other.extra_env["GIT_CEILING_DIRECTORIES"] == "/slots:/home"
    pinned = VIEWS.checkouts(Path("/slots/s1"), git_dir=Path("/repo/.git/worktrees/s1"))
    assert isinstance(pinned, RealRepo)
    assert pinned.extra_env["GIT_AUTHOR_EMAIL"] == pinned.extra_env["GIT_COMMITTER_EMAIL"] == "task-loop@localhost"
    assert "GIT_AUTHOR_EMAIL" not in view.extra_env  # the person's own checkout commits as the person
    monkeypatch.setenv("GIT_CONFIG_COUNT", "two")
    with pytest.raises(GitUnavailable, match="GIT_CONFIG_COUNT"):
        VIEWS.checkouts(Path("/nowhere"))


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
    monkeypatch.setattr(owned_processes, "observe_owned", lambda identity: asked.append(identity) or ProcessObservation(seen))
    monkeypatch.setattr(owned_processes, "group_alive", lambda pgid: asked.append(pgid) or group)
    assert worker_gone(Worker(pid=42, pgid=41, start="s", boot="b")) is expected
    assert asked[0] == OwnedProcess(42, 41, "s", "b")


def test_a_mise_shim_path_keeps_its_trust_and_the_xdg_and_ca_names() -> None:
    names = {"MISE_TRUSTED_CONFIG_PATHS": "/w", "MISE_DATA_DIR": "/d", "XDG_CONFIG_HOME": "/c", "NODE_EXTRA_CA_CERTS": "/ca"}
    assert scrubbed({**BASE, **names}) == BASE | names | BAR
