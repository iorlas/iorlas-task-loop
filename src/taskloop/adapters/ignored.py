"""Ignore matching stays in the shell because it writes a temporary excludes file."""
import contextlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError


def ignored_by(git: Git, wt: str | Path, rules: list[str], paths: Iterable[str]) -> set[str]:
    """The subset of `paths` that `rules` ignore (the user's own global excludes are not replaced; only the rules given are read)."""
    with tempfile.NamedTemporaryFile("w", suffix=".ignore", delete=False, encoding="utf-8") as f:
        f.write("\n".join(rules) + "\n")
        ex = f.name
    try:
        return set(git.check_ignore(str(wt), list(paths), excludes=ex))
    except SlotGitError:
        return set()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(ex)
