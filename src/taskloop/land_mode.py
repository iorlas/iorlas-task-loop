"""Who lands a task whose checks passed (tl-8bh9.14.136): the profile's `land` key at origin's `main` as fetched now, read
from Git objects only (never a working tree), through the one profile reader. A round asks it only when a passed task waits."""

from collections.abc import Callable
from pathlib import Path

from git_porcelain import GitUnavailable, NotARepo

from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.git_views import GitProfileFiles
from taskloop.land_policy import LandPolicy
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


def known_policy(checkouts: Checkouts) -> Callable[[Path], LandPolicy]:
    """Read one immutable known origin main and its policy without fetching or writing Git."""
    def read(checkout: Path) -> LandPolicy:
        try:
            repo = checkouts(checkout.expanduser().resolve())
            commit = next((each.sha for each in repo.refs([TRACKING]) if each.name == TRACKING), None)
            if commit is None:
                return LandPolicy()
            found = read_profile(GitProfileFiles(checkout, checkouts), commit)
            return LandPolicy(found.land if isinstance(found, Profile) else None, commit)
        except (GitUnavailable, NotARepo, OSError, RuntimeError):
            return LandPolicy()
    return read


def known_slot_policy(checkouts: Checkouts, files: SlotFiles) -> Callable[[Path, str], LandPolicy]:
    """Read the policy from the repository an adopted slot's verified pointer belongs to."""
    policy = known_policy(checkouts)
    def read(slot: Path, repo_id: str) -> LandPolicy:
        try:
            root = repository(checkouts, files, str(slot), repo_id)
            return LandPolicy() if isinstance(root, str) else policy(root)
        except (GitUnavailable, NotARepo, OSError, RuntimeError):
            return LandPolicy()
    return read


def known_mode(checkouts: Checkouts) -> Callable[[Path], LandMode | None]:
    """The dashboard's read: the `land` key at the last fetched origin `main` (`refs/remotes/origin/main`; no fetch, a local read
    only), None when it cannot be read (no checkout, no fetch yet, no valid profile): the dashboard then claims no policy."""

    policy = known_policy(checkouts)
    return lambda checkout: policy(checkout).mode


def cached_mode(read: Callable[[Path], LandMode | None], checkout: Path, monotonic: Callable[[], float],
                seconds: float = 30.0) -> Callable[[], LandMode | None]:
    """`read` for one checkout, asked again at most every `seconds` (a board poll reads it once per card of the land column)."""
    held: list[tuple[float, LandMode | None]] = []

    def mode() -> LandMode | None:
        now = monotonic()
        if not held or now - held[0][0] >= seconds:
            held[:] = [(now, read(checkout))]
        return held[0][1]

    return mode
