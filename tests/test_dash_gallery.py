"""The owner-look gallery: items from metadata `looks` (or an old description), pictures served only when an item names
them, good / redo / undo through bd (faked in memory), the signal in the Roadmap's strip."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import gallery  # noqa: E402
import signals  # noqa: E402

NOW = 1_800_000_000.0
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def shots(label="menu"):
    return [{"path": "docs/evidence/tl-1/%s-before.png" % label, "role": "before", "label": label},
            {"path": "docs/evidence/tl-1/%s.png" % label, "role": "after", "label": label}]


def looks(*statuses):
    return [{"id": "tl-1#%d" % k, "bead": "tl-1", "title": "menu reads well %d" % k, "note": "judge: fine", "shots": shots("m%d" % k),
             "status": s} for k, s in enumerate(statuses, 1)]


class FakeBd:
    """The few bd commands the gallery runs, over a dict of beads."""

    def __init__(self, beads):
        self.beads, self.calls, self.n = beads, [], 0

    def __call__(self, repo, *args, timeout=30):
        self.calls.append(args)
        out, code = "", 0
        if args[0] == "show":
            b = self.beads.get(args[1])
            out, code = (json.dumps([b]), 0) if b else ("", 1)
        elif args[0] == "update" and "--metadata" in args:
            self.beads[args[1]]["metadata"] = json.loads(args[args.index("--metadata") + 1])
        elif args[0] == "update" and "--status" in args:
            self.beads[args[1]]["status"] = args[args.index("--status") + 1]
        elif args[0] == "close":
            self.beads[args[1]]["status"] = "closed"
        elif args[0] == "create":
            self.n += 1
            nid = "tl-r%d" % self.n
            self.beads[nid] = {"id": nid, "title": args[1], "status": "open", "description": args[args.index("--description") + 1], "labels": []}
            out = json.dumps({"id": nid})
        return subprocess.CompletedProcess(args, code, out, "")


def world(*statuses, status="open"):
    return FakeBd({"tl-look": {"id": "tl-look", "title": "Look review", "status": status, "labels": [gallery.LABEL],
                               "metadata": {"looks": looks(*statuses), "other": 1}, "description": ""}})


class Items(unittest.TestCase):
    def test_metadata_items(self):
        fake = world("open", "good")
        with mock.patch.object(gallery, "bd", fake):
            items = gallery.collect("/r", [{"id": "tl-look", "labels": [gallery.LABEL], "created_at": "2026-10-23T10:00:00Z"},
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
        got = gallery.items_of("b", {"metadata": {"looks": ["x", {"no": "id"}, {"id": "a#1", "shots": ["z", {"path": "p.png"}], "status": "weird"}]}})
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
        data, ctype = gallery.picture(str(self.repo), "docs/evidence/tl-1/m1.png", self.items)
        self.assertEqual((data, ctype), (PNG, "image/png"))

    def test_only_listed_pictures(self):
        for rel in ("../secret.png", "docs/evidence/tl-1/other.png", "/etc/passwd", "docs/evidence/tl-1/m1.png/../../../../secret.png", ""):
            self.assertIsNone(gallery.picture(str(self.repo), rel, self.items), rel)

    def test_a_listed_path_that_escapes_the_repo_is_not_read(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "../secret.png"}]}]}})
        self.assertIsNone(gallery.picture(str(self.repo), "../secret.png", items))

    def test_lfs_pointer_and_missing_file_are_not_pictures(self):
        (self.repo / "docs/evidence/tl-1/m1.png").write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:0\n")
        with mock.patch.object(gallery.subprocess, "run", side_effect=OSError):
            self.assertIsNone(gallery.picture(str(self.repo), "docs/evidence/tl-1/m1.png", self.items))

    def test_a_non_picture_extension_is_refused(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "docs/x.html"}]}]}})
        self.assertIsNone(gallery.picture(str(self.repo), "docs/x.html", items))


class Answers(unittest.TestCase):
    def ask(self, fake, verdict, item="tl-1#1", note=""):
        with mock.patch.object(gallery, "bd", fake):
            return gallery.answer("/r", {"look_bead": "tl-look", "item": item, "verdict": verdict, "note": note}, now=NOW)

    def stored(self, fake):
        return {e["id"]: e for e in fake.beads["tl-look"]["metadata"]["looks"]}

    def test_good_settles_the_item_and_keeps_the_other_metadata(self):
        fake = world("open", "open")
        code, out = self.ask(fake, "good")
        self.assertEqual((code, out["status"], out["open"]), (200, "good", 1))
        self.assertEqual(self.stored(fake)["tl-1#1"]["status"], "good")
        self.assertEqual(fake.beads["tl-look"]["metadata"]["other"], 1)
        self.assertEqual(fake.beads["tl-look"]["status"], "open")

    def test_the_last_good_closes_the_look_bead(self):
        fake = world("good", "open")
        self.ask(fake, "good", item="tl-1#2")
        self.assertEqual(fake.beads["tl-look"]["status"], "closed")

    def test_redo_files_a_bead_with_the_note_and_the_pictures(self):
        fake = world("open")
        code, out = self.ask(fake, "redo", note="  the title is too small  ")
        self.assertEqual((code, out["status"]), (200, "redo"))
        made = fake.beads[out["redo_bead"]]
        self.assertIn("the title is too small", made["description"])
        self.assertIn("docs/evidence/tl-1/m1.png (after)", made["description"])
        self.assertIn("docs/evidence/tl-1/m1-before.png (before)", made["description"])
        self.assertTrue(any(c[0] == "create" and "related:tl-1" in c for c in fake.calls))
        e = self.stored(fake)["tl-1#1"]
        self.assertEqual((e["status"], e["redo_bead"], e["answer_note"]), ("redo", out["redo_bead"], "the title is too small"))
        self.assertEqual(fake.beads["tl-look"]["status"], "closed")  # nothing waits any more

    def test_redo_needs_a_note(self):
        fake = world("open")
        code, out = self.ask(fake, "redo", note="   ")
        self.assertEqual((code, out["code"]), (400, "empty"))
        self.assertFalse(any(c[0] == "create" for c in fake.calls))

    def test_second_answer_finds_it_answered(self):
        fake = world("open")
        self.ask(fake, "good")
        code, out = self.ask(fake, "redo", note="n")
        self.assertEqual((code, out["code"]), (409, "answered"))
        self.assertFalse(any(c[0] == "create" for c in fake.calls))

    def test_undo_of_good_reopens_item_and_bead(self):
        fake = world("open")
        self.ask(fake, "good")
        self.assertEqual(fake.beads["tl-look"]["status"], "closed")
        code, out = self.ask(fake, "undo")
        self.assertEqual((code, out["status"]), (200, "open"))
        self.assertEqual((self.stored(fake)["tl-1#1"]["status"], fake.beads["tl-look"]["status"]), ("open", "open"))

    def test_undo_of_redo_closes_the_follow_up(self):
        fake = world("open")
        _, out = self.ask(fake, "redo", note="n")
        self.ask(fake, "undo")
        self.assertEqual(fake.beads[out["redo_bead"]]["status"], "closed")
        e = self.stored(fake)["tl-1#1"]
        self.assertEqual((e["status"], e["redo_bead"]), ("open", ""))

    def test_undo_of_an_open_item_changes_nothing(self):
        fake = world("open")
        self.assertEqual(self.ask(fake, "undo")[0], 200)
        self.assertFalse(any(c[0] in ("close", "create") for c in fake.calls))

    def test_unknown_item_bead_and_bad_input(self):
        fake = world("open")
        self.assertEqual(self.ask(fake, "good", item="tl-1#9")[1]["code"], "item_missing")
        with mock.patch.object(gallery, "bd", fake):
            self.assertEqual(gallery.answer("/r", {"look_bead": "nope", "item": "x", "verdict": "good"})[0], 404)
            for bad in ({"look_bead": "--db=x", "item": "a", "verdict": "good"}, {"look_bead": "tl-look", "item": "a", "verdict": "x"}, [], None):
                self.assertEqual(gallery.answer("/r", bad)[0], 400, bad)
        fake.beads["plain"] = {"id": "plain", "labels": ["auto"], "metadata": {"looks": looks("open")}}
        with mock.patch.object(gallery, "bd", fake):  # not an owner-look bead: never touched
            self.assertEqual(gallery.answer("/r", {"look_bead": "plain", "item": "tl-1#1", "verdict": "good"})[0], 404)

    def test_an_old_description_bead_is_turned_into_metadata_by_the_first_answer(self):
        desc = "## tl-9: Settings\n- docs/e/tl-9/a.png\n"
        fake = FakeBd({"tl-look": {"id": "tl-look", "status": "open", "labels": [gallery.LABEL], "description": desc}})
        with mock.patch.object(gallery, "bd", fake):
            code, _ = gallery.answer("/r", {"look_bead": "tl-look", "item": "tl-9#0", "verdict": "good"}, now=NOW)
        self.assertEqual(code, 200)
        self.assertEqual(fake.beads["tl-look"]["metadata"]["looks"][0]["status"], "good")

    def test_bd_failing_reports_and_changes_nothing_else(self):
        fake = world("open")
        orig = fake.__call__
        fake.__class__ = type("Bad", (FakeBd,), {"__call__": lambda s, repo, *a, timeout=30: subprocess.CompletedProcess(a, 1, "", "boom")
                                                  if a[0] == "update" else orig(repo, *a)})
        code, out = self.ask(fake, "good")
        self.assertEqual((code, out["code"]), (502, "bd"))
        self.assertEqual(fake.beads["tl-look"]["status"], "open")


class Hardening(unittest.TestCase):
    def test_a_backslash_path_from_windows_matches(self):
        items = gallery.items_of("b", {"metadata": {"looks": [{"id": "a#1", "shots": [{"path": "docs\\e\\a.png"}]}]}})
        self.assertEqual(items[0]["shots"][0]["path"], "docs/e/a.png")

    def test_a_failed_save_closes_the_redo_bead_it_made(self):
        fake = world("open")
        orig = fake.__call__
        fake.__class__ = type("Bad", (FakeBd,), {"__call__": lambda s, repo, *a, timeout=30: subprocess.CompletedProcess(a, 1, "", "boom")
                                                  if a[0] == "update" and "--metadata" in a and a[1] == "tl-look" else orig(repo, *a)})
        with mock.patch.object(gallery, "bd", fake):
            code, _ = gallery.answer("/r", {"look_bead": "tl-look", "item": "tl-1#1", "verdict": "redo", "note": "n"}, now=NOW)
        self.assertEqual(code, 502)
        self.assertEqual(fake.beads["tl-r1"]["status"], "closed")

    def test_two_clicks_at_once_file_one_follow_up(self):
        import threading
        fake = world("open")
        res = []
        with mock.patch.object(gallery, "bd", fake):
            ts = [threading.Thread(target=lambda: res.append(gallery.answer("/r", {"look_bead": "tl-look", "item": "tl-1#1", "verdict": "redo", "note": "n"})[0]))
                  for _ in range(4)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(sorted(res), [200, 409, 409, 409])
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "create"), 1)

    def test_an_odd_redo_id_is_never_closed(self):
        fake = world("open")
        fake.beads["tl-look"]["metadata"]["looks"][0].update(status="redo", redo_bead="--force")
        with mock.patch.object(gallery, "bd", fake):
            gallery.answer("/r", {"look_bead": "tl-look", "item": "tl-1#1", "verdict": "undo"})
        self.assertFalse(any(c[0] == "close" and "--force" in c for c in fake.calls))


class Signal(unittest.TestCase):
    def test_looks_waiting(self):
        self.assertEqual(signals.looks_waiting([], NOW), [])
        (s,) = signals.looks_waiting([{"bead": "tl-1", "filed": NOW - 3600}, {"bead": "tl-2", "filed": NOW - 60}], NOW)
        self.assertEqual((s["kind"], s["sev"], s["href"], s["title"]), ("looks", "info", "#looks", "2 looks wait for you"))
        (old,) = signals.looks_waiting([{"bead": "tl-1", "filed": NOW - 13 * 3600}], NOW)
        self.assertEqual((old["sev"], old["title"]), ("amber", "1 look wait for you"))


class RoadmapStrip(unittest.TestCase):
    def test_open_looks_reach_the_signal_strip_and_answered_ones_do_not(self):
        import graph
        import roadmap
        g = graph.build([], {"pick_label": "auto", "skip_labels": []}, set(), set(), (), now=NOW)
        out = roadmap.build(g, [], [], [], [], {}, now=NOW, looks=[{"bead": "tl-1", "filed": NOW - 60}])
        self.assertEqual([s["title"] for s in out["signals"] if s["kind"] == "looks"], ["1 look wait for you"])
        out = roadmap.build(g, [], [], [], [], {}, now=NOW)
        self.assertFalse([s for s in out["signals"] if s["kind"] == "looks"])


class Api(unittest.TestCase):
    def test_api_and_post(self):
        import server
        fake = world("open")
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / "demo"
            (repo / "docs/evidence/tl-1").mkdir(parents=True)
            (repo / "docs/evidence/tl-1/m1.png").write_bytes(PNG)
            cfg = Path(home) / "cfg" / "task-loop"
            cfg.mkdir(parents=True)
            (cfg / "repos.json").write_text(json.dumps({str(repo): {}}))
            env = {"HOME": home, "XDG_CONFIG_HOME": str(cfg.parent), "APPDATA": str(cfg.parent)}
            with mock.patch.dict(os.environ, env), mock.patch.object(gallery, "bd", fake), \
                    mock.patch.object(server, "beads_of", lambda r: [{"id": "tl-look", "labels": [gallery.LABEL]}]):
                server._cache.clear()
                out = server.api_looks("demo")
                self.assertEqual((out["repo"], out["summary"]["open"]), ("demo", 1))
                url = out["items"][0]["shots"][1]["url"]
                self.assertTrue(url.startswith("/api/look-shot?repo=demo&path=docs"), url)
                self.assertEqual(server.look_shot("demo", "docs/evidence/tl-1/m1.png"), (PNG, "image/png"))
                self.assertIsNone(server.look_shot("demo", "docs/evidence/tl-1/nope.png"))
                self.assertEqual(server.answer_look({"repo": "demo", "look_bead": "tl-look", "item": "tl-1#1", "verdict": "good"})[0], 200)
                self.assertEqual(server.api_looks("demo")["summary"], {"open": 0, "good": 1, "redo": 0})
                self.assertEqual(server.api_looks("")["repo"], "demo")  # a bare #looks means the first repo
                self.assertEqual(server.answer_look({"repo": "nowhere"})[0], 404)


if __name__ == "__main__":
    unittest.main()
