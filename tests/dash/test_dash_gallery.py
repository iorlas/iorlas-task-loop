"""The owner-look gallery: items from metadata `looks` (or an old description), pictures served only when an item names
them, the page's answer through POST /api/look and the `look` port. The verb itself: tests/asks/test_look_verb.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from asks.dash_ports import answering  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from support.look_world import looks, world  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.contracts import gallery  # noqa: E402

LOOKS = make_dash().looks

NOW = 1_800_000_000.0
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def using(fake):
    return mock.patch.object(LOOKS.env.ports, "store", lambda repo: fake)


class Items(unittest.TestCase):
    def test_metadata_items(self):
        fake = world("open", "good")
        with using(fake):
            items = LOOKS.collect("/r", [{"id": "tl-look", "labels": [gallery.LABEL], "created_at": "2026-10-23T10:00:00Z"},
                                           {"id": "x", "labels": ["auto"]}])
        self.assertEqual([i["status"] for i in items], ["open", "good"])
        self.assertEqual([s["role"] for s in items[0]["shots"]], ["before", "after"])
        self.assertTrue(items[0]["filed"] > 0)
        self.assertEqual(gallery.summary(items), {"open": 1, "good": 1, "redo": 0})

    def test_old_bead_falls_back_to_the_description(self):
        desc = ("## tl-9: Settings screen\nScreenshots of tl-9 (Settings screen), committed with its land:\n- docs/e/tl-9/a.png\n"
                "- docs/e/tl-9/b.jpg\n\nWhat the agent judged: ok\n\n## tl-8: Other\nNothing to see")
        got = gallery.parse_description(desc, "tl-look")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["id"], got[0]["bead"], got[0]["title"]), ("tl-9#0", "tl-9", "Settings screen"))
        self.assertEqual([s["role"] for s in got[0]["shots"]], ["after", "after"])

    def test_junk_in_metadata_is_skipped(self):
        got = gallery.items_of(
            "b", {"metadata": {"looks": ["x", {"no": "id"}, {"id": "a#1", "shots": ["z", {"path": "p.png"}], "status": "weird"}]}}
        )
        self.assertEqual([(i["id"], i["status"], len(i["shots"])) for i in got], [("a#1", "open", 1)])


class Pictures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / "docs/evidence/tl-1").mkdir(parents=True)
        (self.repo / "docs/evidence/tl-1/m1.png").write_bytes(PNG)
        (Path(self.tmp.name) / "secret.png").write_bytes(PNG)
        self.items = gallery.items_of("tl-look", {"metadata": {"looks": looks("open")}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_listed_picture_is_served(self):
        data, ctype = must(LOOKS.picture(str(self.repo), "docs/evidence/tl-1/m1.png", self.items))
        self.assertEqual((data, ctype), (PNG, "image/png"))

    def test_only_listed_pictures(self):
        for rel in ("../secret.png", "docs/evidence/tl-1/other.png", "/etc/passwd", "docs/evidence/tl-1/m1.png/../../../../secret.png", ""):
            self.assertIsNone(LOOKS.picture(str(self.repo), rel, self.items), rel)

    def test_a_listed_path_that_escapes_the_repo_is_not_read(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "../secret.png"}]}]}})
        self.assertIsNone(LOOKS.picture(str(self.repo), "../secret.png", items))

    def test_lfs_pointer_and_missing_file_are_not_pictures(self):
        (self.repo / "docs/evidence/tl-1/m1.png").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:0\n")
        self.assertIsNone(LOOKS.picture(str(self.repo), "docs/evidence/tl-1/m1.png", self.items))

    def test_a_non_picture_extension_is_refused(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "docs/x.html"}]}]}})
        self.assertIsNone(LOOKS.picture(str(self.repo), "docs/x.html", items))


class Hardening(unittest.TestCase):
    def test_a_backslash_path_from_windows_matches(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "docs\\e\\a.png"}]}]}})
        self.assertEqual(items[0]["shots"][0]["path"], "docs/e/a.png")


class ShotUrl(unittest.TestCase):
    def test_a_picture_kept_as_an_artifact_is_served_by_the_artifact_url(self):
        self.assertEqual(LOOKS.shot_url("demo", "artifact:tl-1/a b.png"), "/api/artifact?bead=tl-1&name=a%20b.png")
        self.assertEqual(LOOKS.shot_url("demo", "docs/a.png"), "/api/look-shot?repo=demo&path=docs/a.png")


class Api(unittest.TestCase):
    def test_items_pictures_and_the_answer(self):
        fake = world("open")
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "demo"
            (repo / "docs/evidence/tl-1").mkdir(parents=True)
            (repo / "docs/evidence/tl-1/m1.png").write_bytes(PNG)
            cfg = Path(home) / "cfg" / "task-loop"
            cfg.mkdir(parents=True)
            (cfg / "repos.json").write_text(json.dumps({str(repo): {}}))
            env = {"HOME": home, "XDG_CONFIG_HOME": str(cfg.parent), "APPDATA": str(cfg.parent)}
            with mock.patch.dict(os.environ, env):
                dash = make_dash(home=home)
            dash.env.ports = answering(lambda repo: fake, home)
            with mock.patch.object(dash.env.ports, "store", lambda repo: fake), \
                    mock.patch.object(dash.beads, "beads_of", lambda r: [{"id": "tl-look", "labels": [gallery.LABEL]}]):
                path, items = dash.looks.look_items("demo")
                self.assertEqual((Path(path).name, [i["status"] for i in items]), ("demo", ["open"]))
                self.assertEqual(dash.looks.look_shot("demo", "docs/evidence/tl-1/m1.png"), (PNG, "image/png"))
                self.assertIsNone(dash.looks.look_shot("demo", "docs/evidence/tl-1/nope.png"))
                good = {"project": "demo", "bead": "tl-1#1", "verdict": "good", "note": ""}
                self.assertEqual(dash.writes.post("look", good), (200, {"ok": True, "message": ""}))
                self.assertEqual([i["status"] for i in dash.looks.look_items("demo")[1]], ["good"])
                self.assertFalse(dash.writes.post("look", dict(good, project="nowhere"))[1]["ok"])
                self.assertFalse(dash.writes.post("look", dict(good, verdict="redo"))[1]["ok"])  # redo needs a note

if __name__ == "__main__":
    unittest.main()
