"""The land's reads of origin's `main` as fetched now (O), in Git objects only (tl-8bh9.14.8 section 5): the fetch and the
required names at O, S (the squash of X onto O) with the tree listings of S, X and O, and what S changes in the gate
(`land_gate`), refused unless the person accepted it."""

from collections.abc import Callable
from pathlib import Path

from git_porcelain import Conflicted, GitUnavailable, MissingRevision, Repo, Sha, Squashed

from taskloop.check_admit import named
from taskloop.check_store import ChecksRow, Required
from taskloop.land_gate import gate_of
from taskloop.land_push import Origin, fetched
from taskloop.land_summary import gate_lines, message_at
from taskloop.operations import Failed
from taskloop.profile import ProfileFiles, Unavailable, read_profile

type Files = dict[str, tuple[str, Sha]]
type Profiles = Callable[[Path], ProfileFiles]


def required_at(profiles: Profiles, checkout: Path, o: str) -> Required | Failed:
    """The profile at O (the remote target's immutable objects) and its required names with their argv digests at O:
    `target_profile`, `target`, `no_required` as the checks admission refuses them."""
    profile = read_profile(profiles(checkout), o)
    if isinstance(profile, Unavailable):
        return Failed("unavailable", "git", profile.detail)
    found = named(o, profile)
    return found[1] if isinstance(found, tuple) else Failed("refused", found.reason, found.detail.replace("at main", f"at origin main {o}"))


def fetched_target(profiles: Profiles, origin: Origin) -> tuple[str, Required] | Failed:
    """Origin's `main` as fetched now (O) and the required names at O."""
    try:
        o = fetched(origin.repo)
    except GitUnavailable as error:
        return Failed("unavailable", "remote", f"`origin` could not be fetched ({type(error).__name__}): rerun.")
    if o is None:
        return Failed("refused", "target", "`origin` has no branch `main` to land on.")
    required = required_at(profiles, origin.checkout, o)
    return required if isinstance(required, Failed) else (o, required)


def made_s(origin: Origin, checks: ChecksRow, title: str, o: str, source: str | None = None) -> Squashed | Conflicted | Failed:
    """S made in Git objects only, with section 9's message."""
    x = source or checks.commit
    try:
        return origin.repo.squash(o, x, message_at(origin.repo, title, checks, o))
    except MissingRevision:
        return Failed("refused", "commit_missing", f"The checked commit {x} is not in the repository.")
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not merge X onto origin's main ({type(error).__name__}): rerun.")


def _files(repo: Repo, rev: str) -> Files:
    """A commit's tree listing (path to mode and blob): two trees are the same exactly when their listings are."""
    tree = repo.tree(rev)
    if tree is None:
        raise MissingRevision(rev)
    return dict(tree.files)


def squashed_onto(origin: Origin, checks: ChecksRow, title: str, o: str,
                  source: str | None = None) -> tuple[str, Files, Files, Files] | Conflicted | Failed:
    """S, with the tree listings of S, X and O, or the typed conflict for ordinary land's handoff."""
    x, made = checks.commit, made_s(origin, checks, title, o, source)
    if isinstance(made, (Conflicted, Failed)):
        return made
    try:
        return made.sha, _files(origin.repo, made.sha), _files(origin.repo, x), _files(origin.repo, o)
    except MissingRevision:
        return Failed("refused", "commit_missing", f"The checked commit {x} is not in the repository.")
    except GitUnavailable as error:
        return Failed("unavailable", "git", f"Git could not merge X onto origin's main ({type(error).__name__}): rerun.")


def gated(profiles: Profiles, origin: Origin, accepted: bool, o: str, s: str) -> Failed | None:
    """What S changes in the gate against O (`land_gate`): refused, naming each fact, unless `--accept-gate-changes`."""
    gate = gate_of(origin, profiles(origin.checkout), o, s)
    if isinstance(gate, Failed) or not gate.decisive or accepted:
        return gate if isinstance(gate, Failed) else None
    return Failed("refused", "gate_changed", "\n".join(["S changes what decides a pass (nothing was recorded):", *gate_lines(gate)]))
