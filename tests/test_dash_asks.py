"""The dash reads and answers the current ask version only; its answers land as AskAnswer records."""
import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
import types
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401
from support.narrow import must  # noqa: E402
from asks.samples import MOCKS  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from taskloop.contracts import codec  # noqa: E402
from taskloop.contracts.ask import Ask  # noqa: E402
from taskloop.contracts.enums import AskStatus  # noqa: E402
from taskloop.contracts.stores import ORPHAN  # noqa: E402
from taskloop_dash.env import Ports  # noqa: E402

ASK = dataclasses.replace(MOCKS["lifesim-22b3"], bead="b-1", id="b-1-1")


def fake_bd(repo, *args, timeout=30):
    return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")


class DashAsks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dash = make_dash(Ports(bd=fake_bd), config=self.tmp.name)
        self.path = self.dash.env.config.ask("b-1")
        self.path.parent.mkdir(parents=True)

    def put(self, rec=ASK, **over):
        self.path.write_text(json.dumps({**codec.to_json(rec), **over}))

    def read(self):
        return codec.from_json(Ask, json.loads(self.path.read_text()))

    def test_the_inbox_shows_the_fields_as_the_page_reads_them(self):
        self.put()
        row = self.dash.asks.inbox()[0]
        self.assertEqual((row["id"], row["question"], len(row["options"])), ("b-1-1", ASK.decision, 3))
        self.assertEqual(row["options"][0]["then"], ASK.options[0].consequence)

    def test_a_dropped_ask_is_listed_as_one_typed_line_for_its_bead(self):
        self.put(v=1)
        (row,) = self.dash.asks.inbox()
        self.assertEqual((row["bead"], row["question"], row["orphan"], row["options"]), ("b-1", ORPHAN, True, []))

    def test_an_old_or_unknown_version_is_absent(self):
        for v in (1, 9):
            self.put(v=v)
            self.assertEqual((self.dash.asks.ask_file("b-1"), self.dash.asks.open_ask("b-1")), ({}, None))  # absent, but listed as dropped

    def test_a_typed_option_lands_as_an_ask_answer_and_the_first_wins(self):
        self.put()
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "option": 2})[0], 200)
        got = self.read()
        given = must(got.answer)
        self.assertEqual((got.status, given.action, given.by, given.text), (AskStatus.ANSWERED, "text", "dash", "Split the bead"))
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "text": "x"})[1]["code"], "answered")
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "text": "better", "amend": True})[0], 200)
        self.assertEqual(must(self.read().answer).text, "better")

    def test_words_are_a_text_answer_and_empty_is_refused(self):
        self.put()
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "text": " "})[0], 400)
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "text": "go with A"})[0], 200)
        self.assertEqual(must(self.read().answer).text, "go with A")
        self.assertEqual(self.dash.asks.answer({"ask": "b-9-1", "text": "x"})[0], 404)

    def test_a_newer_ask_supersedes_and_withdraw_keeps_the_record_valid(self):
        self.put()
        code, out = self.dash.asks.answer({"ask": "b-1-0", "text": "x"})
        self.assertEqual((code, out["code"], out["new_ask"]), (409, "superseded", "b-1-1"))
        self.assertEqual(self.dash.asks.withdraw({"ask": "b-1-1", "why": "moot"})[0], 200)
        got = self.read()
        self.assertEqual((got.status, got.closed_why), (AskStatus.WITHDRAWN, "moot"))
        self.assertEqual(self.dash.asks.answer({"ask": "b-1-1", "text": "x"})[0], 410)


class AskFailures(unittest.TestCase):
    """Every way an answer can fail says what is true and what to do, never a raw bd line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.calls = []
        self.bd_says = types.SimpleNamespace(returncode=0, stdout="[]", stderr="")
        self.dash = make_dash(Ports(bd=self.bd), config=self.tmp.name)
        self.dir = self.dash.env.config.ask("x").parent
        self.dir.mkdir(parents=True)

    def bd(self, repo, *args, timeout=30):
        self.calls.append(args)
        return self.bd_says

    def ask(self, bead="x-1", n=1, **over):
        rec = dataclasses.replace(ASK, bead=bead, id="%s-%d" % (bead, n), repo=str(self.d), t=time.time(), parks_at=time.time() + 9e4)
        (self.dir / ("%s.json" % bead)).write_text(json.dumps({**codec.to_json(rec), **over}))

    def read(self, bead="x-1"):
        return json.loads((self.dir / ("%s.json" % bead)).read_text())

    def test_a_bead_bd_does_not_know_says_the_ask_is_out_of_date(self):
        self.bd_says = types.SimpleNamespace(returncode=1, stdout="", stderr='Error: resolving demo: no issue found matching "demo"')
        self.ask("demo")
        code, out = self.dash.asks.answer({"ask": "demo-1", "text": "b"})
        self.assertEqual((code, out["code"]), (404, "bead_missing"))
        self.assertNotIn("resolving", out["error"])
        self.assertIn("dismiss", out["error"])

    def test_any_other_bd_failure_keeps_its_last_line(self):
        self.bd_says = types.SimpleNamespace(returncode=1, stdout="", stderr="boom: disk full")
        self.ask()
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "bd"))
        self.assertIn("boom: disk full", out["error"])
        self.assertEqual(self.read()["answer"]["text"], "b")  # the answer is the record; only opening the bead failed

    def test_no_bd_on_the_path_is_an_error_message_not_a_dropped_connection(self):
        self.ask()
        with mock.patch.object(self.dash.env.ports, "bd", side_effect=FileNotFoundError(2, "No such file or directory")):
            code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "no_bd"))

    def test_a_withdrawn_ask_says_why_and_is_not_listed(self):
        self.ask()
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": "fixed in 0.23.5"})[0], 200)
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (410, "withdrawn"))
        self.assertEqual(self.dash.asks.inbox(), [])
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1"})[0], 200)  # twice is fine

    def test_an_ask_the_engine_replaced_points_at_the_new_one(self):
        self.ask(n=2)
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"], out["new_ask"]), (409, "superseded", "x-1-2"))
        self.assertEqual(self.dash.asks.answer({"ask": "nope-1", "text": "b"})[1]["code"], "gone")

    def test_withdraw_leaves_the_bead_alone(self):
        self.ask()
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": "stale"})[0], 200)
        self.assertEqual((self.read()["status"], self.read()["closed_why"]), ("withdrawn", "stale"))
        self.assertEqual(self.calls, [])

    def test_the_inbox_is_ordered_by_what_each_ask_unblocks_and_drops_closed_beads(self):
        (self.d / ".beads").mkdir()
        beads = [{"id": "a", "status": "open"}, {"id": "b", "status": "open"}, {"id": "c", "status": "closed"},
                 {"id": "d", "status": "open", "dependencies": [{"type": "blocks", "id": "b"}]},
                 {"id": "e", "status": "open", "dependencies": [{"type": "blocks", "id": "b"}]}]
        for bead in ("a", "b", "c"):
            self.ask(bead)
        with mock.patch.object(self.dash.beads, "beads_of", return_value=beads):
            rows = self.dash.asks.inbox()
        self.assertEqual([(r["bead"], r["unblocks"]) for r in rows], [("b", 2), ("a", 0)])

    def test_odd_requests_get_an_error_not_a_crash(self):
        self.ask()
        for body in ([], "x", {"ask": ["x-1-1"], "text": "b"}, {"ask": "../../etc-1", "text": "b"}, {"ask": "x-1-1", "text": 5}):
            self.assertIn(self.dash.asks.answer(body)[0], (400, 404, 409))
        self.assertEqual(self.dash.asks.withdraw([])[0], 400)
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": 7})[0], 200)
        self.assertEqual(self.read()["closed_why"], "dismissed by the owner")

    def test_a_new_bead_missing_from_a_stale_listing_is_not_hidden_but_an_old_gone_one_is(self):
        (self.d / ".beads").mkdir()
        self.ask("fresh")
        self.ask("old", t=time.time() - 3600)
        with mock.patch.object(self.dash.beads, "beads_of", return_value=[{"id": "zzz", "status": "open"}]):
            self.assertEqual([r["bead"] for r in self.dash.asks.inbox()], ["fresh"])

    def test_a_second_process_reuses_the_bead_list_of_the_last_30_seconds(self):
        """tl-u08: tl ask list is a fresh process every time; bd list takes seconds under load, so it is read once per 30 s."""
        (self.d / ".beads").mkdir()
        dash = make_dash(config=self.tmp.name)  # the default bd port: a real subprocess call
        out = mock.Mock(returncode=0, stdout=json.dumps([{"id": "a", "status": "open"}]), stderr="")
        with mock.patch.object(subprocess, "run", return_value=out) as run, mock.patch.object(shutil, "which", return_value="/bin/bd"):
            dash.env.ttl.clear()
            self.assertEqual(dash.beads.beads_of(str(self.d)), [{"id": "a", "status": "open"}])
            dash.env.ttl.clear()  # a new process: nothing in memory
            self.assertEqual(dash.beads.beads_of(str(self.d)), [{"id": "a", "status": "open"}])
        self.assertEqual(run.call_count, 1)

    def test_amend_replaces_an_unused_answer_and_a_used_one_is_final(self):
        self.ask()
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "first"})[0], 200)
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "second"})
        self.assertEqual((code, out["code"]), (409, "answered"))
        self.assertIn("--amend", out["error"])
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "second", "amend": True})[0], 200)
        self.assertEqual(self.read()["answer"]["text"], "second")
        self.dash.asks.store.consume("x-1", time.time())  # a run used it
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "third", "amend": True})
        self.assertEqual((code, out["code"]), (409, "consumed"))
        self.ask("y")  # no answer yet: amend is just the first answer
        self.assertEqual(self.dash.asks.answer({"ask": "y-1", "text": "one", "amend": True})[0], 200)

    def test_withdrawing_an_answered_but_unused_ask_drops_it_and_a_used_one_cannot_be(self):
        self.ask()
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "go with B"})[0], 200)
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": "wrong ask"})[0], 200)
        self.assertEqual(self.read()["status"], "withdrawn")
        self.ask("z")
        self.dash.asks.answer({"ask": "z-1", "text": "go"})
        self.dash.asks.store.consume("z", time.time())
        self.assertEqual(self.dash.asks.withdraw({"ask": "z-1"})[1]["code"], "consumed")

    def test_a_parked_ask_is_listed_last_flagged_and_answerable(self):
        self.ask("quiet", status="parked")
        self.ask("loud")
        rows = self.dash.asks.inbox()
        self.assertEqual([(r["bead"], r["parked"]) for r in rows], [("loud", False), ("quiet", True)])
        self.assertEqual(self.dash.asks.answer({"ask": "quiet-1", "text": "go on"})[0], 200)


if __name__ == "__main__":
    unittest.main()
