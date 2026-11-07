"""One retention table for the config folder's logs nothing else prunes: land-push evidence and a loop's death records (tl-7i9k.24)."""
import os
from pathlib import Path

import pytest

from taskloop.app.prune import retention
from tlkernel.paths import ConfigDir

DAY = 86400.0
NOW = 100 * DAY


def put(root: Path, name: str, age_days: float) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def test_old_files_of_each_area_go_and_fresh_ones_stay(workdir):
    root = Path(workdir)
    old = [put(root, "land-push/1-a.log", 40), put(root, "repos/k/loop/died-9.json", 40)]
    kept = [put(root, "land-push/2-b.log", 1), put(root, "repos/k/loop/died-10.json", 5), put(root, "repos/k/loop/died-11.json", 20)]
    gone = retention.prune(ConfigDir(root), keep_days=14, now=NOW, dry_run=False)
    assert sorted(g.path for g in gone) == sorted(old)
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in kept)


def test_a_dry_run_names_the_same_files_and_removes_none(workdir):
    root = Path(workdir)
    old = put(root, "land-push/1-a.log", 40)
    gone = retention.prune(ConfigDir(root), keep_days=14, now=NOW, dry_run=True)
    assert [g.path for g in gone] == [old]
    assert old.exists()


def folder(root: Path, name: str, age_days: float) -> Path:
    path = put(root, name + "/f", age_days).parent
    os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
    return path


def test_files_outside_the_table_are_never_touched(workdir):
    root = Path(workdir)
    other = [put(root, "repos/k/loop/exits.jsonl", 400), put(root, "repos/k/loop/log.jsonl", 400),
             put(root, "repos/k/loop/loop-1.log", 400),
             put(root, "factory.db", 400)]
    assert retention.prune(ConfigDir(root), keep_days=14, now=NOW, dry_run=False) == []
    assert all(p.exists() for p in other)


@pytest.mark.parametrize("keep_days", [60, 90])
def test_a_longer_configured_age_stretches_every_area(workdir, keep_days):
    root = Path(workdir)
    put(root, "land-push/1-a.log", 40)
    assert retention.prune(ConfigDir(root), keep_days=keep_days, now=NOW, dry_run=False) == []


def test_old_scratch_folders_of_the_engines_own_prefixes_go_and_nothing_else(workdir):
    root = Path(workdir)
    old = [folder(root, "tl-land-gate-ab12", 3), folder(root, "tl-land-merge-cd34", 3),
           folder(root, "tl-check-home-ef56", 3)]
    kept = [folder(root, "tl-land-gate-new", 0.2), folder(root, "wd-1", 30), folder(root, "other", 30)]
    gone = retention.prune_scratch(root, now=NOW, dry_run=False)
    assert sorted(g.path for g in gone) == sorted(old)
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in kept)


def test_a_dry_run_of_the_scratch_prune_removes_none(workdir):
    root = Path(workdir)
    old = folder(root, "tl-land-gate-ab12", 3)
    assert [g.path for g in retention.prune_scratch(root, now=NOW, dry_run=True)] == [old]
    assert old.exists()
