"""The owner's push and the morning digest (tl-bxk.12.2), and the counts for the coordinator (tl-bxk.8.25)."""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import digest  # noqa: E402
import notifier  # noqa: E402
import tl  # noqa: E402

DAY = time.mktime((2026, 10, 24, 12, 0, 0, 0, 0, -1))  # local noon, so the hour rules do not depend on when the suite runs


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.d), "APPDATA": str(self.d), "HOME": str(self.d),
                                         "USERPROFILE": str(self.d)})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        (self.d / "task-loop").mkdir()

    def channel(self, text):
        (self.d / "task-loop" / "notify").write_text(text)


class Notifier(Env):
    def test_the_channel_is_a_command_desktop_or_off(self):
        self.assertEqual(notifier.channel()[0], "off")
        self.channel("echo hi\n")
        self.assertEqual(notifier.channel(), ("command", "echo hi"))
        self.channel("Desktop\n")
        self.assertEqual(notifier.channel()[0], "desktop")
        self.channel("off")
        self.assertEqual(notifier.channel()[0], "off")
        self.assertEqual(notifier.send("verify", "x"), "off")

    def test_a_command_gets_the_ask_and_the_whole_digest_in_its_environment(self):
        self.channel("curl ntfy")
        with mock.patch.object(notifier.subprocess, "Popen") as po:
            self.assertEqual(notifier.send("digest", "one line", bead="b", ask_id="b-1", full="the\nwhole"), "sent")
        env = po.call_args.kwargs["env"]
        self.assertEqual((env["TL_ASK_KIND"], env["TL_ASK_BEAD"], env["TL_ASK_ID"], env["TL_ASK_TEXT"], env["TL_DIGEST_TEXT"]),
                         ("digest", "b", "b-1", "one line", "the\nwhole"))
        self.assertEqual(po.call_args.args[0], "curl ntfy")

    def test_desktop_says_so_when_this_machine_cannot_show_one(self):
        self.channel("desktop")
        with mock.patch.object(notifier, "desktop", return_value=False):
            self.assertTrue(notifier.send("verify", "x").startswith("failed"))
        with mock.patch.object(notifier, "desktop", return_value=True) as dk:
            self.assertEqual(notifier.send("verify", "x", bead="lifesim-1"), "sent")
        self.assertEqual(dk.call_args.args[0], "task-loop: lifesim-1")


class Signals(Env):
    def test_refusals_dns_and_flakes_are_counted_from_the_engines_own_records_in_the_window(self):
        eng = self.d / "task-loop" / "engine"
        eng.mkdir()
        recs = [{"kind": "warn", "t": 100, "text": "write was denied `x`"},
                {"kind": "warn", "t": 101, "text": "`unity-tests` failed (exit 1), retrying: it is marked flaky"},
                {"kind": "note", "t": 102, "text": "push: Could not resolve host: github.com"},
                {"kind": "msg", "t": 103, "text": "the model said denied and flaky and Could not resolve host"},
                {"kind": "warn", "t": 5000, "text": "denied outside the window"}]
        (eng / "lifesim-a-20261023-010101.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
        (eng / "lifesim-b-20261023-010101.stderr").write_text("fatal: Temporary failure in name resolution\n")
        os.utime(eng / "lifesim-a-20261023-010101.jsonl", (time.time(), time.time()))
        (eng / "lifesim-c-20200101-000000.stderr").write_text("fatal: Temporary failure in name resolution\n")  # an old run
        recs2 = [{"kind": "warn", "t": 104, "text": "git: Permission denied (publickey)"}]
        with (eng / "lifesim-a-20261023-010101.jsonl").open("a") as fh:
            fh.write("\n" + json.dumps(recs2[0]))
        lo = time.mktime((2026, 10, 22, 0, 0, 0, 0, 0, -1))
        sig = digest.signals(50, 1000)  # the .stderr run of 2026-10-23 is outside this window of epoch seconds
        self.assertEqual((sig["refused"]["count"], sig["flake"]["count"], sig["dns"]["count"]), (1, 1, 1))
        self.assertEqual(sig["dns"]["beads"], {"lifesim-a": 1})
        sig = digest.signals(lo, time.mktime((2026, 10, 25, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(sig["dns"]["beads"].get("lifesim-b"), 1)
        self.assertNotIn("lifesim-c", sig["dns"]["beads"])


class Compose(unittest.TestCase):
    def test_the_digest_has_the_night_the_asks_and_the_coordinators_counts(self):
        card = {"repo": "/x/lifesim", "beads": 12, "landed": 8, "landed_no_ask": 6, "parked": 1, "paused": 2, "failed": 1,
                "crashes": 0, "lost": 0}
        sig = {"refused": {"count": 3, "beads": {"a": 2, "b": 1}}, "dns": {"count": 0, "beads": {}},
               "flake": {"count": 5, "beads": {"c": 5}}}
        one, full = digest.compose(DAY - 86400, DAY, scorecards=[card], sig=sig, asks=(4, 2, ["lifesim-x: Over its time limit (unblocks 3)"]))
        self.assertEqual(one, "last 24h: 8 landed, 4 asks open, 2 paused, 1 failed")
        for want in ("landed 8 of 12 beads (6 with no ask)", "asked and waiting: 4 (+2 parked after 3 days)", "lifesim: 8 landed, 1 failed",
                     "lifesim-x: Over its time limit (unblocks 3)", "commands refused: 3 (a x2, b x1)", "DNS or network errors: 0",
                     "flakes retried: 5 (c x5)"):
            self.assertIn(want, full)


class Due(Env):
    def at(self, hour):
        return datetime.fromtimestamp(DAY).replace(hour=hour).timestamp()

    def test_due_after_seven_once_a_day(self):
        self.assertIsNone(digest.due(self.at(6)))
        since, until = digest.due(self.at(8))
        self.assertEqual(until - since, 86400)
        (self.d / "task-loop" / "digest.json").write_text(json.dumps({"sent": self.at(7) + 60}))
        self.assertIsNone(digest.due(self.at(9)))
        (self.d / "task-loop" / "digest.json").write_text(json.dumps({"sent": self.at(7) - 86400 + 60}))
        since, _ = digest.due(self.at(8))
        self.assertEqual(since, self.at(7) - 86400 + 60)  # covers the time since the last one

    def test_a_try_in_the_last_two_hours_blocks_another(self):
        (self.d / "task-loop" / "digest.json").write_text(json.dumps({"tried": self.at(8) - 600}))
        self.assertIsNone(digest.due(self.at(8)))

    def test_a_garbled_state_file_does_not_stop_the_digest(self):
        (self.d / "task-loop" / "digest.json").write_text(json.dumps({"sent": "x", "tried": None}))
        self.assertIsNotNone(digest.due(self.at(8)))

    def test_the_loop_starts_it_detached_only_with_a_channel(self):
        self.assertEqual(digest.maybe_send(self.at(8)), "")
        (self.d / "task-loop" / "notify").write_text("echo")
        with mock.patch.object(digest.subprocess, "Popen") as po:
            self.assertEqual(digest.maybe_send(self.at(8)), "started")
            self.assertEqual(digest.maybe_send(self.at(8)), "")  # tried: not again for two hours
        cmd = po.call_args.args[0]
        self.assertEqual(cmd[2:4], ["digest", "--send"])
        self.assertEqual(po.call_count, 1)


if __name__ == "__main__":
    unittest.main()
