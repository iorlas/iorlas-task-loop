"""Slot state of a vanished slot goes; a live slot's folder, a young one and a repo that cannot be resolved are never touched."""
import os
from pathlib import Path

from taskloop.app.prune import slotstate
from tlkernel.ids import loop_key
from tlkernel.paths import ConfigDir
from tlkernel.slots import Checkout

DAY = 86400.0
NOW = 100 * DAY
ORIGIN = "https://example.test/acme/widgets.git"


class StubGit:
    """The two reads of the port that the pruner uses."""

    def __init__(self, trees: dict[str, list[str]], origins: dict[str, str]) -> None:
        self.trees, self.origins = trees, origins

    def checkouts(self, d: str) -> list[Checkout]:
        return [Checkout(path=p, branch="", main=False) for p in self.trees[d]]

    def remote_url(self, d: str, remote: str) -> str:
        return self.origins[d]


def folder(root: Path, key: str, slot: str, age_days: float) -> Path:
    path = root / "repos" / key / "slot-state" / slot
    (path / "tmp").mkdir(parents=True)
    (path / "tmp" / "scratch").write_text("x")
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def test_only_an_old_folder_of_a_vanished_slot_goes(workdir):
    root = Path(workdir)
    key = loop_key("/r")
    live = folder(root, key, "slot-1", 90)
    orphan = folder(root, key, "slot-gone", 90)
    young = folder(root, key, "slot-new", 2)
    git = StubGit({"/r": ["/w/slot-1", "/r"]}, {"/r": ORIGIN})
    gone = slotstate.prune(ConfigDir(root), ["/r"], git, NOW, dry_run=False)
    assert [g.path for g in gone] == [orphan]
    assert live.exists() and young.exists() and not orphan.exists()


def test_a_dry_run_names_the_orphan_and_removes_nothing(workdir):
    root = Path(workdir)
    orphan = folder(root, loop_key("/r"), "slot-gone", 90)
    gone = slotstate.prune(ConfigDir(root), ["/r"], StubGit({"/r": ["/r"]}, {"/r": ORIGIN}), NOW, dry_run=True)
    assert [g.path for g in gone] == [orphan]
    assert orphan.exists()


def test_the_state_of_a_repo_no_registered_checkout_resolves_to_is_kept(workdir):
    root = Path(workdir)
    stranger = folder(root, loop_key("/x"), "slot-1", 90)
    assert slotstate.prune(ConfigDir(root), ["/r"], StubGit({"/r": ["/r"]}, {"/r": ORIGIN}), NOW, dry_run=False) == []
    assert stranger.exists()
