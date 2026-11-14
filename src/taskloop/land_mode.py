"""Who lands a task whose checks passed (tl-8bh9.14.136): the profile's `land` key at origin's `main` as fetched now, read
from Git objects only (never a working tree), through the one profile reader. A round asks it only when a passed task waits."""

from collections.abc import Callable
from pathlib import Path

from git_porcelain import GitUnavailable, NotARepo

from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.git_views import GitProfileFiles
from taskloop.land_push import TRACKING, fetched
from taskloop.operations import Failed
from taskloop.profile import LandMode, Profile, Refused, Unavailable, read_profile
from taskloop.slot_state import repository


def land_mode(remotes: Checkouts) -> Callable[[Path], LandMode | Failed]:
    """The reader over the person's checkout through the remote-capable view: `unavailable:remote` when `origin` cannot be
    fetched, `refused:target` without a `main`, `refused:target_profile` for a profile that is missing or invalid there."""

    def read(checkout: Path) -> LandMode | Failed:
        path = checkout.expanduser().resolve()
        try:
            o = fetched(remotes(path))
        except (GitUnavailable, NotARepo) as error:
            return Failed("unavailable", "remote", f"`origin` could not be fetched ({type(error).__name__}): the next round asks again.")
        if o is None:
            return Failed("refused", "target", "`origin` has no branch `main` to land on.")
        found = read_profile(GitProfileFiles(path, remotes), o)
        if isinstance(found, Unavailable):
            return Failed("unavailable", "git", found.detail)
        if isinstance(found, Refused):
            return Failed("refused", "target_profile", f"{found.reason}: {found.detail}")
        assert isinstance(found, Profile)
        return found.land

    return read


def known_mode(checkouts: Checkouts) -> Callable[[Path], LandMode | None]:
    """Read the profile at one resolved, last-known origin main commit; no fetch or Git writes."""

    def read(checkout: Path) -> LandMode | None:
        try:
            path = checkout.expanduser().resolve()
            commit = next((ref.sha for ref in checkouts(path).refs([TRACKING]) if ref.name == TRACKING), None)
            if commit is None:
                return None
            found = read_profile(GitProfileFiles(path, checkouts), commit)
            return found.land if isinstance(found, Profile) else None
        except (GitUnavailable, NotARepo, OSError, RuntimeError):
            return None

    return read


def known_slot_mode(checkouts: Checkouts, files: SlotFiles) -> Callable[[Path, str], LandMode | None]:
    """Resolve a slot's repository identity, regardless of its current task branch, before reading policy at the root."""
    policy = known_mode(checkouts)

    def read(slot: Path, repo_id: str) -> LandMode | None:
        if not repo_id:
            return None
        try:
            root = repository(checkouts, files, str(slot), repo_id)
            return None if isinstance(root, str) else policy(root)
        except (GitUnavailable, NotARepo, OSError, RuntimeError):
            return None

    return read
