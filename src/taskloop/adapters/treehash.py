"""What git says of a worktree: the tree it would commit now (without touching the real index), the state that decides that tree, and the
paths the base's .gitignore files ignore."""
import contextlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from git_porcelain import real_cache, real_parse

from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError

State = tuple[bytes, tuple[object, ...]]


class TreeHashError(RuntimeError):
    """Porcelain could not snapshot the worktree: a failed read or temporary-index write must never become a tree id."""


def tree_of(git: Git, wt: str | Path) -> TreeSha:
    """The worktree as git would commit it now, untracked files included."""
    try:
        return TreeSha(git.tree_of(str(wt)))
    except SlotGitError as e:
        raise TreeHashError(e.tail) from None


def state_of(git: Git, wt: str | Path) -> State | None:
    """One status plus porcelain's content signature; None when unreadable or too large to memoize.

    Keep the caller's State shape while sharing snapshot's invalidation rules, including symlink text and same-tick edits.
    Ignored untracked inputs belong to InputKeys, not this whole-tree identity.
    """
    out = git.worktree_state(str(wt))
    if out is None:
        return None
    text = out.decode("utf-8", "surrogateescape")
    state = real_parse.parse_status(text)
    key = real_cache.tree_key(Path(wt), text, (*state.tracked, *state.untracked))
    return (out, (key,)) if key is not None else None


def ignore_rules(base: str, lines_of: dict[str, list[str]]) -> list[str]:
    """The base's .gitignore files as one rule list, each rule anchored to the folder its file sits in."""
    rules: list[str] = []
    for path, lines in lines_of.items():
        d = path[:-len(".gitignore")].rstrip("/")
        for raw in lines:
            ln = raw.rstrip()
            if not ln or ln.startswith("#"):
                continue
            neg, pat = ("!", ln[1:]) if ln.startswith("!") else ("", ln)
            if not d:
                rules.append(ln)
            elif pat.startswith("/"):
                rules.append(f"{neg}/{d}{pat}")
            elif "/" in pat.rstrip("/"):
                rules.append(f"{neg}/{d}/{pat}")
            else:
                rules.append(f"{neg}/{d}/**/{pat}")
    return rules


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
