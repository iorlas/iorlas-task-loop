"""Construct the real Git boundary for native command input."""

from pathlib import Path

from git_porcelain import RealRepo

from taskloop.repo import RepoInspection, UnsupportedCheckout, inspect_repo


def inspect_checkout(path: str) -> RepoInspection:
    """Resolve the native path once and request fresh shared-library observations."""
    try:
        expanded = Path(path).expanduser()
    except RuntimeError as error:
        raise UnsupportedCheckout(f"Cannot expand checkout path: {path}") from error
    checkout = expanded.resolve()
    return inspect_repo(RealRepo(checkout, memoize=False), checkout)
