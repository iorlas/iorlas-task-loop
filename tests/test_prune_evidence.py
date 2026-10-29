"""Evidence kept once: a retry's identical picture is a link, never a second copy; a run keeps at most its cap and counts drops."""
import errno
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401

from taskloop.app.look import keep, shots


def png(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class Keeping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.shots = self.root / "shots"
        self.wt = self.root / "wt-evidence"  # the worktree's evidence dir
        self.run1, self.run2 = self.root / "runs" / "x-1-1" / "evidence", self.root / "runs" / "x-1-2" / "evidence"

    def keeper(self, run, cap=keep.CAP_BYTES, earlier=()):
        return keep.Keeper([self.wt, run], list(earlier), cap)

    def test_the_same_picture_on_a_retry_is_a_hard_link_to_the_first_copy_not_a_second_copy(self):
        src = png(self.shots / "a.png", b"P" * 4096)
        first = self.keeper(self.run1)
        self.assertTrue(first.keep(src, self.run1 / "a.png"))
        retry = self.keeper(self.run2, earlier=[self.run1])  # a rerun of the bead: its own run folder
        self.assertTrue(retry.keep(src, self.run2 / "a.png"))
        a, b = os.stat(self.run1 / "a.png"), os.stat(self.run2 / "a.png")
        self.assertEqual((a.st_ino, a.st_nlink), (b.st_ino, 2))
        added = keep.used_bytes([self.run2], [self.run1])  # the retry's folder holds nothing the first run does not
        self.assertEqual((keep.used_bytes([self.run1]), added), (4096, 0))

    def test_a_round_that_renders_the_same_picture_again_adds_no_bytes(self):
        k = self.keeper(self.run1)
        for rnd in range(3):
            self.assertTrue(k.keep(png(self.shots / "a.png", b"Q" * 1000), self.wt / f"{rnd}-a.png"))
        self.assertEqual({os.stat(self.wt / f"{rnd}-a.png").st_ino for rnd in range(3)}.__len__(), 1)  # one file, three names
        self.assertEqual(keep.used_bytes([self.wt]), 1000)  # the three names are one file, counted once

    def test_a_different_picture_is_copied(self):
        k = self.keeper(self.run1)
        k.keep(png(self.shots / "a.png", b"A" * 100), self.run1 / "a.png")
        k.keep(png(self.shots / "b.png", b"B" * 100), self.run1 / "b.png")
        self.assertNotEqual(os.stat(self.run1 / "a.png").st_ino, os.stat(self.run1 / "b.png").st_ino)

    def test_a_link_across_disks_falls_back_to_a_copy(self):
        src = png(self.shots / "a.png", b"P" * 100)
        self.keeper(self.run1).keep(src, self.run1 / "a.png")
        with mock.patch.object(os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.assertTrue(self.keeper(self.run2, earlier=[self.run1]).keep(src, self.run2 / "a.png"))
        self.assertEqual((self.run2 / "a.png").read_bytes(), b"P" * 100)
        self.assertEqual(os.stat(self.run2 / "a.png").st_nlink, 1)

    def test_a_kept_file_is_replaced_not_written_through_so_the_first_copy_stays_whole(self):
        k = self.keeper(self.run1)
        k.keep(png(self.shots / "a.png", b"one" * 50), self.wt / "a.png")
        k.keep(self.wt / "a.png", self.run1 / "a.png")  # linked
        k.keep(png(self.shots / "a.png", b"two" * 50), self.wt / "a.png")  # the next round, other bytes, same name
        self.assertEqual((self.run1 / "a.png").read_bytes(), b"one" * 50)
        self.assertEqual((self.wt / "a.png").read_bytes(), b"two" * 50)

    def test_the_cap_drops_new_content_and_counts_it_but_never_a_twin(self):
        k = self.keeper(self.run1, cap=250)
        self.assertTrue(k.keep(png(self.shots / "a.png", b"A" * 100), self.run1 / "a.png"))
        self.assertTrue(k.keep(png(self.shots / "b.png", b"B" * 100), self.run1 / "b.png"))
        self.assertFalse(k.keep(png(self.shots / "c.png", b"C" * 100), self.run1 / "c.png"))
        self.assertFalse((self.run1 / "c.png").exists())
        self.assertEqual(k.dropped, 1)
        self.assertTrue(k.keep(self.shots / "a.png", self.run1 / "again.png"))  # identical to a.png: a link, free
        self.assertEqual(k.dropped, 1)

    def test_the_dirs_are_walked_once_not_per_file(self):
        for i in range(500):
            png(self.run1 / f"old{i}.png", bytes([i % 251]) * (i + 10))
        k = self.keeper(self.run2, earlier=[self.run1])
        started = time.monotonic()
        with mock.patch.object(Path, "rglob", side_effect=AssertionError("walked again")), \
                mock.patch.object(keep.filecmp, "cmp", wraps=keep.filecmp.cmp) as cmp:
            for i in range(500):
                self.assertTrue(k.keep(png(self.shots / f"n{i}.png", bytes([i % 251]) * (i + 10)), self.run2 / f"n{i}.png"))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(cmp.call_count, 500)  # one byte comparison per file: only its same-size twin
        self.assertEqual(keep.used_bytes([self.run2], [self.run1]), 0)
        self.assertEqual(k.used, 0)

    def test_the_default_cap_is_200_mb(self):
        self.assertEqual(keep.CAP_BYTES, 200 * 1024 * 1024)


class Host:
    """The engine as Pictures sees it: a worktree evidence dir, a run folder, the cap and a log."""

    def __init__(self, root, run, cap_mb=200):
        self.bead, self.evidence_dir, self.run_dir = "x-1", root / "wt" / "evidence", root / "runs" / run
        self.cfg, self.notes = mock.Mock(evidence_cap_mb=cap_mb, look_max_px=1280), []
        self.log = mock.Mock(note=self.notes.append)


class PicturesKeepOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = mock.patch.object(shots.looks, "downscale")
        p.start()
        self.addCleanup(p.stop)

    def test_a_rerun_of_a_bead_keeps_its_pictures_as_links_to_the_first_runs(self):
        src = png(self.root / "raw" / "a.png", b"P" * 5000)
        for run in ("x-1-1", "x-1-2"):
            host = Host(self.root, run)
            host.evidence_dir.parent.joinpath("evidence").mkdir(parents=True, exist_ok=True)
            shots.Pictures(host).keep_picture(src, [], self.root / "base")
            (host.run_dir / "evidence").mkdir(parents=True, exist_ok=True)
            self.assertEqual(len(shots.Pictures(host).keep_evidence()), 1)
        first, second = (self.root / "runs" / r / "evidence" / "a.png" for r in ("x-1-1", "x-1-2"))
        self.assertEqual(os.stat(first).st_ino, os.stat(second).st_ino)

    def test_over_the_cap_the_picture_is_dropped_and_the_log_counts_it(self):
        host = Host(self.root, "x-1-1", cap_mb=0)
        pics = shots.Pictures(host)
        pics.keep_picture(png(self.root / "raw" / "a.png", b"P" * 10), [], self.root / "base")
        self.assertFalse((host.evidence_dir / "a.png").exists())
        self.assertEqual(len(host.notes), 1)
        self.assertIn("1 file(s) not kept", host.notes[0])


if __name__ == "__main__":
    unittest.main()
