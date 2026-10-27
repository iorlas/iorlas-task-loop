"""Test helpers: git that answers to the test alone, an in-memory ``FakeRepo``, and a runner for set-up commands.

``FakeRepo`` / ``FakeWorktree`` (with ``FakeRemote``) implement the same :class:`~git_porcelain.api.Repo` and
``Worktree`` protocols as ``RealRepo`` with commits, trees, refs, worktrees, a paused rebase, config, hooks (as
knobs) and remotes in memory and no subprocess. A host's tests take a ``Repo`` and pass a ``FakeRepo``; the package's
contract suite runs one set of scenarios against both so the fake cannot drift from the binary.

``hermetic_env`` returns the environment that shuts the machine's git out of a test: no system or
global config, no variable pointing git at another repository, and the settings a test needs
passed through ``GIT_CONFIG_*`` (command-line scope, so a repository's own config cannot undo
them). ``apply_hermetic_env`` sets it through a pytest ``monkeypatch``. Neither imports pytest.

The quiet set (no hooks, no auto-maintenance, no signing, no template) is the default and is
opt-out: a test of a hook or of maintenance passes ``config={}``. The identity is a parameter;
``None`` leaves git with no ``user.*`` at all.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Final, Protocol

from git_porcelain.fake import FakeRemote, FakeRepo, FakeWorktree

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from git_porcelain.history import Identity

__all__ = ["LEAKS", "QUIET", "FakeRemote", "FakeRepo", "FakeWorktree", "apply_hermetic_env", "git", "hermetic_env"]

#: Settings every test git process runs with unless the test asks otherwise.
QUIET: Final[Mapping[str, str]] = {
    "maintenance.auto": "false",
    "gc.auto": "0",
    "core.hooksPath": "/dev/null",
    "commit.gpgSign": "false",
    "init.templateDir": "",
}

#: Variables git honours that would point a test's git at another repository or config.
LEAKS: Final = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_CONFIG_PARAMETERS",
    "GIT_LFS_SKIP_SMUDGE",
)


class _Env(Protocol):
    """The part of ``pytest.MonkeyPatch`` this module uses."""

    def setenv(self, name: str, value: str, prepend: str | None = None) -> None: ...
    def delenv(self, name: str, raising: bool = ...) -> None: ...  # noqa: FBT001 — MonkeyPatch's own signature


def hermetic_env(*, identity: Identity | None = None, config: Mapping[str, str] = QUIET, home: Path | None = None) -> dict[str, str | None]:
    """The variables to set (a value) or remove (``None``) so git reads only what the test gives it."""
    env: dict[str, str | None] = dict.fromkeys(LEAKS)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    pairs = list(config.items())
    if identity is not None:
        pairs += [("user.name", identity.name), ("user.email", identity.email)]
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    if home is not None:
        env["HOME"] = str(home)
    return env


def apply_hermetic_env(
    monkeypatch: _Env,
    *,
    identity: Identity | None = None,
    config: Mapping[str, str] = QUIET,
    home: Path | None = None,
) -> None:
    """Set :func:`hermetic_env` through ``monkeypatch``; a later ``setenv`` in the test wins."""
    for name, value in hermetic_env(identity=identity, config=config, home=home).items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def git(cwd: Path, *args: str) -> str:
    """Run ``git -C cwd *args`` and return stdout; a failure raises with git's stderr in the message."""
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        msg = f"git {' '.join(args)} failed ({done.returncode}) in {cwd}: {done.stderr.strip()}"
        raise AssertionError(msg)
    return done.stdout
