"""The owner-look gallery: items from metadata `looks` (or an old description), pictures served only when an item names
them, the page's v1 answer through the `look` port, the signal in the Roadmap's strip. The verb itself: tests/asks/test_look_verb.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from asks.dash_ports import answering  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from support.look_world import looks, world  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.contracts import gallery  # noqa: E402
from taskloop_dash.views import graph, roadmap, signals  # noqa: E402

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


class Signal(unittest.TestCase):
    def test_a_picture_kept_as_an_artifact_is_served_by_the_artifact_url(self):
        self.assertEqual(LOOKS.shot_url("demo", "artifact:tl-1/a b.png"), "/api/artifact?bead=tl-1&name=a%20b.png")
        self.assertEqual(LOOKS.shot_url("demo", "docs/a.png"), "/api/look-shot?repo=demo&path=docs/a.png")

    def test_looks_waiting(self):
        self.assertEqual(signals.looks_waiting([], NOW), [])
        (s,) = signals.looks_waiting([{"bead": "tl-1", "filed": NOW - 3600}, {"bead": "tl-2", "filed": NOW - 60}], NOW)
        self.assertEqual((s["kind"], s["sev"], s["href"], s["title"]), ("looks", "info", "#looks", "2 looks wait for you"))
        (old,) = signals.looks_waiting([{"bead": "tl-1", "filed": NOW - 13 * 3600}], NOW)
        self.assertEqual((old["sev"], old["title"]), ("amber", "1 look wait for you"))


class RoadmapStrip(unittest.TestCase):
    def test_open_looks_reach_the_signal_strip_and_answered_ones_do_not(self):
        g = graph.build([], {"pick_label": "auto", "skip_labels": []}, set(), set(), (), now=NOW)
        out = roadmap.build(g, [], [], [], [], {}, now=NOW, looks=[{"bead": "tl-1", "filed": NOW - 60}])
        self.assertEqual([s["title"] for s in out["signals"] if s["kind"] == "looks"], ["1 look wait for you"])
        out = roadmap.build(g, [], [], [], [], {}, now=NOW)
        self.assertFalse([s for s in out["signals"] if s["kind"] == "looks"])


class Api(unittest.TestCase):
    def test_api_and_post(self):
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
                out = dash.looks.api_looks("demo")
                self.assertEqual((out["repo"], out["summary"]["open"]), ("demo", 1))
                url = out["items"][0]["shots"][1]["url"]
                self.assertTrue(url.startswith("/api/look-shot?repo=demo&path=docs"), url)
                self.assertEqual(dash.looks.look_shot("demo", "docs/evidence/tl-1/m1.png"), (PNG, "image/png"))
                self.assertIsNone(dash.looks.look_shot("demo", "docs/evidence/tl-1/nope.png"))
                self.assertEqual(
                    dash.looks.answer_look({"repo": "demo", "look_bead": "tl-look", "item": "tl-1#1", "verdict": "good"})[0], 200
                )
                self.assertEqual(dash.looks.api_looks("demo")["summary"], {"open": 0, "good": 1, "redo": 0})
                self.assertEqual(dash.looks.api_looks("")["repo"], "demo")  # a bare #looks means the first repo
                gone = {"repo": "nowhere", "look_bead": "tl-look", "item": "x", "verdict": "good"}
                self.assertEqual(dash.looks.answer_look(gone)[0], 404)
                self.assertEqual(dash.looks.answer_look({"repo": "demo"})[0], 400)
                no_note = {"repo": "demo", "look_bead": "tl-look", "item": "tl-1#1", "verdict": "redo"}
                self.assertEqual(dash.looks.answer_look(no_note)[0], 409)


if __name__ == "__main__":
    unittest.main()
