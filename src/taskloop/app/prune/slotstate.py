"""Slot state (a slot's temp and toolchain scratch under repos/<key>/slot-state/<slot>) of a slot that no longer exists. A slot's folder is
reused across beads, so only a folder whose slot is not a worktree of its repo now, and that has sat unchanged for MIN_AGE_DAYS, goes."""
import shutil
from pathlib import Path
from typing import Final, Protocol

from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.slots import Checkout, SlotGitError

from taskloop.app.prune.runs import Gone, size_of
from tlslots.paths import slot_state_roots

MIN_AGE_DAYS: Final = 14


class SlotGit(Protocol):
    """The read of the Git port the pruner uses."""

    def checkouts(self, d: str) -> list[Checkout]: ...


def prune(cfg: ConfigDir, repos: list[str], git: SlotGit, now: float, dry_run: bool) -> list[Gone]:
    """Remove (name, with `dry_run`) the orphan slot folders of every registered repo. The repo's state folder is found the way the engine
    makes it (ids.loop_key of the repo); a repo whose worktrees git cannot list keeps all its slots,
    and state of a repo not in `repos` is left alone."""
    old = _old_folders(cfg, now)
    gone: list[Gone] = []
    for repo in repos if old else []:  # git is asked only when some folder is old enough to go
        try:
            slots = {Path(c.path).name for c in git.checkouts(repo)}
        except SlotGitError:
            continue
        for path in old.get(loop_key(repo), []):
            if path.name in slots:
                continue
            size = size_of(path)
            if not dry_run:
                try:
                    shutil.rmtree(path)
                except OSError:
                    continue
            gone.append(Gone(path, size))
    return gone


def _old_folders(cfg: ConfigDir, now: float) -> dict[str, list[Path]]:
    """{state key: the slot folders unchanged for MIN_AGE_DAYS}, read from disk only."""
    out: dict[str, list[Path]] = {}
    for state in slot_state_roots(cfg):
        for path in sorted(state.glob("*")):
            try:
                if path.is_dir() and path.stat().st_mtime < now - MIN_AGE_DAYS * 86400:
                    out.setdefault(state.parent.name, []).append(path)
            except OSError:
                continue
    return out
