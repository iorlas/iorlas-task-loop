"""Every scratch folder, once: the one place that decides where temporary files live (stdlib only, no OS path literal).

A scratch folder is a child of `<cache root>/task-loop/tmp` ($XDG_CACHE_HOME or ~/.cache), never the system temp dir and never under
~/.config (a test run may not open anything there: tests/delegate/hermetic.py). The cache root sits on the user's own disk, as the
checkout does, so git discovery never crosses a mount (a tmpfs /tmp made "not a git repository" and "Stopping at filesystem boundary"),
and the same code runs on Mac, Linux and Windows. `TL_SCRATCH` in `env` moves the root (a test run points it into its own home).
Nothing else names /tmp, /var/tmp, `tempfile` or TMPDIR:
tests/rules/test_temp_ratchet.py counts the sites and fails any new one.

The git identity a test commits with is this module's too (`git_identity_env`, `write_git_config`): a test carries its own, never
the host's.
"""
import contextlib
import os
import shutil
import tempfile
from collections.abc import Generator, Mapping
from pathlib import Path

SCRATCH_VAR = "TL_SCRATCH"
IDENTITY = {"GIT_AUTHOR_NAME": "tl test", "GIT_AUTHOR_EMAIL": "test@tl.invalid",
            "GIT_COMMITTER_NAME": "tl test", "GIT_COMMITTER_EMAIL": "test@tl.invalid"}


def scratch_root(env: Mapping[str, str]) -> Path:
    """`$TL_SCRATCH`, else <cache root>/task-loop/tmp ($XDG_CACHE_HOME or ~/.cache). Created here, with its parents."""
    explicit = env.get(SCRATCH_VAR)
    base = Path(explicit) if explicit else Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "task-loop" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def scratch_dir(env: Mapping[str, str], prefix: str = "tl-") -> Path:
    """A new empty folder under the scratch root; the caller removes it (or uses `scratch`)."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=scratch_root(env)))


@contextlib.contextmanager
def scratch(env: Mapping[str, str], prefix: str = "tl-") -> Generator[Path]:
    """A scratch folder for the length of a `with`, removed after."""
    folder = scratch_dir(env, prefix)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def git_identity_env() -> dict[str, str]:
    """The author and committer a test commits as, plus no host git config (the null device on every OS): the test owns its identity."""
    return {**IDENTITY, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def write_git_config(home: Path) -> Path:
    """<home>/.gitconfig with the test identity and `main` as the first branch: what a HOME-isolated run points git at."""
    config = home / ".gitconfig"
    user, mail = IDENTITY["GIT_AUTHOR_NAME"], IDENTITY["GIT_AUTHOR_EMAIL"]
    config.write_text(f"[user]\n\tname = {user}\n\temail = {mail}\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    return config
