"""tl-bxk.8.26: an ask unanswered for 24 h is pushed again (once per 24 h), the looks that wait are pushed once a day."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import tl  # noqa: E402

H = 3600
NOW = 1_800_000_000.0


class Renotify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env = {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.asks = tl.config_dir() / "asks"
        self.asks.mkdir(exist_ok=True)
        self.out = Path(self.tmp.name) / "pushed.txt"
        (tl.config_dir() / "notify").write_text(
            "%s -c \"import os;open(%r,'a').write('|'.join(os.environ.get(k,'') for k in "
            "('TL_ASK_KIND','TL_ASK_BEAD','TL_ASK_ID','TL_ASK_REPEAT','TL_ASK_TEXT'))+'\\n')\"" % (sys.executable, str(self.out)))

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def ask(self, bead, **kw):
        a = {"v": 1, "id": bead + "-1", "bead": bead, "kind": "decision", "status": "open", "question": "**Old format or new?**\nmore",
             "t": NOW - 30 * H, "parks_at": NOW + 40 * H}
        a.update(kw)
        (self.asks / (bead + ".json")).write_text(json.dumps(a))

    def pushed(self, n=1):
        end = time.monotonic() + 60
        while time.monotonic() < end:
            lines = self.out.read_text().splitlines() if self.out.exists() else []
            if len(lines) >= n:
                return lines
            time.sleep(0.05)
        return self.out.read_text().splitlines() if self.out.exists() else []

    def stored(self, bead):
        return json.loads((self.asks / (bead + ".json")).read_text())

    def test_an_old_unanswered_ask_is_pushed_again_once_and_the_clock_restarts(self):
        self.ask("b-old")
        with mock.patch.object(tl, "bd", side_effect=SystemExit):
            self.assertEqual(tl.renotify(now=NOW), [("decision", "b-old-1")])
            (line,) = self.pushed()
            self.assertEqual(line, "decision|b-old|b-old-1|1|Still waiting for you (30 h): Old format or new?")
            a = self.stored("b-old")
            self.assertEqual((a["pushed_at"], a["pushes"]), (NOW, 1))
            self.assertEqual(tl.renotify(now=NOW + 2 * H), [])  # throttled
            self.assertEqual(tl.renotify(every=0, now=NOW + 5 * H), [])  # pushed 5 h ago: not due
            self.assertEqual(len(tl.renotify(every=0, now=NOW + 25 * H)), 1)  # 25 h after the last push
            self.assertEqual(self.stored("b-old")["pushes"], 2)

    def test_young_answered_parked_and_closed_asks_are_not_pushed(self):
        self.ask("b-young", t=NOW - 5 * H)
        self.ask("b-pushed", t=NOW - 40 * H, pushed_at=NOW - 3 * H)
        self.ask("b-answered", answer="use the new one")
        self.ask("b-parked", parks_at=NOW - 1)
        self.ask("b-closed", status="closed")
        with mock.patch.object(tl, "bd", side_effect=SystemExit):
            self.assertEqual(tl.renotify(now=NOW), [])
        self.assertFalse(self.out.exists())

    def test_an_odd_ask_file_is_skipped_and_never_raises(self):
        self.ask("b-bad", parks_at="soon")
        (self.asks / "b-junk.json").write_text("[1, 2]")
        (self.asks / "b-trunc.json").write_text("{")
        self.ask("b-old")
        with mock.patch.object(tl, "bd", side_effect=SystemExit):
            self.assertEqual(tl.renotify(now=NOW), [("decision", "b-old-1")])
        (tl.config_dir() / "repos.json").write_text(json.dumps([5, None]))
        with mock.patch.object(tl, "bd", side_effect=SystemExit):
            self.assertEqual(tl.renotify(every=0, now=NOW + 99 * H), [])  # junk repos.json: no looks, no crash (the ask has parked by now)

    def test_a_push_keeps_an_answer_written_while_it_ran(self):
        self.ask("b-old")
        real = tl.push

        def push_and_answer(*a, **k):
            r = real(*a, **k)
            f = self.asks / "b-old.json"
            d = json.loads(f.read_text())
            d.update(answer="yes", answer_t=NOW)
            f.write_text(json.dumps(d))
            return r
        with mock.patch.object(tl, "bd", side_effect=SystemExit), mock.patch.object(tl, "push", push_and_answer):
            tl.renotify(now=NOW)
        a = self.stored("b-old")
        self.assertEqual((a["answer"], a["pushes"]), ("yes", 1))

    def test_no_notify_command_pushes_nothing_and_breaks_nothing(self):
        (tl.config_dir() / "notify").unlink()
        self.ask("b-old")
        with mock.patch.object(tl, "bd", side_effect=SystemExit):
            tl.renotify(now=NOW)
        self.assertFalse(self.out.exists())

    def test_waiting_looks_are_pushed_once_a_day(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        (tl.config_dir() / "repos.json").write_text(json.dumps({str(repo): {}}))
        rows = [{"id": "r-look1", "status": "open"}, {"id": "r-look2", "status": "in_progress"}, {"id": "r-look3", "status": "closed"}]
        with mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0, stdout=json.dumps(rows), stderr="")):
            self.assertEqual(tl.renotify(every=0, now=NOW), [("look", "looks")])
            (line,) = self.pushed()
            self.assertTrue(line.startswith("look|r-look1|looks-"), line)
            self.assertIn("2 look reviews wait for you", line)
            self.assertEqual(tl.renotify(every=0, now=NOW + 10 * H), [])
            self.assertEqual(tl.renotify(every=0, now=NOW + 25 * H), [("look", "looks")])

    def test_no_looks_waiting_pushes_nothing_but_the_day_is_spent(self):
        repo = Path(self.tmp.name) / "repo"
        repo.mkdir()
        (tl.config_dir() / "repos.json").write_text(json.dumps({str(repo): {}}))
        with mock.patch.object(tl, "bd", return_value=mock.Mock(returncode=0, stdout="[]", stderr="")) as bd:
            self.assertEqual(tl.renotify(every=0, now=NOW), [])
            n = bd.call_count
            tl.renotify(every=0, now=NOW + H)
            self.assertEqual(bd.call_count, n)


if __name__ == "__main__":
    unittest.main()
