"""Evidence kept once: a retry's identical picture is a link, never a second copy; a run keeps at most its cap and counts drops."""
import errno
import os
from pathlib import Path
from unittest import mock

import pytest

from tlartifacts import keep

PNG = b"\x89PNG\r\n\x1a\n"


def png(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class Keeping:
    @pytest.fixture(autouse=True)
    def _dirs(self, tmp_path):
        self.root = tmp_path
        self.shots = self.root / "shots"
        self.wt = self.root / "wt-evidence"  # the worktree's evidence dir
        self.run1, self.run2 = self.root / "runs" / "x-1-1" / "evidence", self.root / "runs" / "x-1-2" / "evidence"

    def keeper(self, run, cap=keep.CAP_BYTES, earlier=()):
        return keep.Keeper([self.wt, run], list(earlier), cap)

    def test_the_same_picture_on_a_retry_is_a_hard_link_to_the_first_copy_not_a_second_copy(self):
        src = png(self.shots / "a.png", b"P" * 4096)
        first = self.keeper(self.run1)
        assert first.keep(src, self.run1 / "a.png")
        retry = self.keeper(self.run2, earlier=[self.run1])  # a rerun of the bead: its own run folder
        assert retry.keep(src, self.run2 / "a.png")
        a, b = os.stat(self.run1 / "a.png"), os.stat(self.run2 / "a.png")
        assert (a.st_ino, a.st_nlink) == (b.st_ino, 2)
        added = keep.used_bytes([self.run2], [self.run1])  # the retry's folder holds nothing the first run does not
        assert (keep.used_bytes([self.run1]), added) == (4096, 0)

    def test_a_round_that_renders_the_same_picture_again_adds_no_bytes(self):
        k = self.keeper(self.run1)
        for rnd in range(3):
            assert k.keep(png(self.shots / "a.png", b"Q" * 1000), self.wt / f"{rnd}-a.png")
        assert {os.stat(self.wt / f"{rnd}-a.png").st_ino for rnd in range(3)}.__len__() == 1  # one file, three names
        assert keep.used_bytes([self.wt]) == 1000  # the three names are one file, counted once

    def test_a_different_picture_is_copied(self):
        k = self.keeper(self.run1)
        k.keep(png(self.shots / "a.png", b"A" * 100), self.run1 / "a.png")
        k.keep(png(self.shots / "b.png", b"B" * 100), self.run1 / "b.png")
        assert os.stat(self.run1 / "a.png").st_ino != os.stat(self.run1 / "b.png").st_ino

    def test_a_link_across_disks_falls_back_to_a_copy(self):
        src = png(self.shots / "a.png", b"P" * 100)
        self.keeper(self.run1).keep(src, self.run1 / "a.png")
        with mock.patch.object(os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            assert self.keeper(self.run2, earlier=[self.run1]).keep(src, self.run2 / "a.png")
        assert (self.run2 / "a.png").read_bytes() == b"P" * 100
        assert os.stat(self.run2 / "a.png").st_nlink == 1

    def test_a_kept_file_is_replaced_not_written_through_so_the_first_copy_stays_whole(self):
        k = self.keeper(self.run1)
        k.keep(png(self.shots / "a.png", b"one" * 50), self.wt / "a.png")
        k.keep(self.wt / "a.png", self.run1 / "a.png")  # linked
        k.keep(png(self.shots / "a.png", b"two" * 50), self.wt / "a.png")  # the next round, other bytes, same name
        assert (self.run1 / "a.png").read_bytes() == b"one" * 50
        assert (self.wt / "a.png").read_bytes() == b"two" * 50

    def test_the_cap_drops_new_content_and_counts_it_but_never_a_twin(self):
        k = self.keeper(self.run1, cap=250)
        assert k.keep(png(self.shots / "a.png", b"A" * 100), self.run1 / "a.png")
        assert k.keep(png(self.shots / "b.png", b"B" * 100), self.run1 / "b.png")
        assert not k.keep(png(self.shots / "c.png", b"C" * 100), self.run1 / "c.png")
        assert not (self.run1 / "c.png").exists()
        assert k.dropped == 1
        assert k.keep(self.shots / "a.png", self.run1 / "again.png")  # identical to a.png: a link, free
        assert k.dropped == 1

    def test_the_dirs_are_walked_once_not_per_file(self):
        for i in range(500):
            png(self.run1 / f"old{i}.png", bytes([i % 251]) * (i + 10))
        k = self.keeper(self.run2, earlier=[self.run1])
        with mock.patch.object(Path, "rglob", side_effect=AssertionError("walked again")), \
                mock.patch.object(keep.filecmp, "cmp", wraps=keep.filecmp.cmp) as cmp:
            for i in range(500):
                assert k.keep(png(self.shots / f"n{i}.png", bytes([i % 251]) * (i + 10)), self.run2 / f"n{i}.png")
        assert cmp.call_count == 500  # one byte comparison per file: only its same-size twin
        assert keep.used_bytes([self.run2], [self.run1]) == 0
        assert k.used == 0

    def test_the_default_cap_is_200_mb(self):
        assert keep.CAP_BYTES == 200 * 1024 * 1024
