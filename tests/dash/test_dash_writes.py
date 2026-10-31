"""POST /api/<verb>: answer, look, cause and ack through the real Intake over a bd in memory; the Result shape; the refused cases."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from asks.dash_ports import answering
from asks.samples import MOCKS
from support.dashes import make_dash
from support.logs import typed
from support.look_world import world
from support.narrow import must
from support.repos import write_repos
from support.runs import manifest

from taskloop.app.run import requests
from taskloop.contracts import wire
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Result
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.run import RunState
from taskloop.contracts.stores import AskStore

NOW = 1_800_000_000.0
ASK = MOCKS["lifesim-22b3"].replace(bead="b-1", id="b-1-1")
RUN = "tl-5-20261026-100000"


class Writes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = world("open")
        self.fake.beads[BeadId("b-1")] = Bead(id=BeadId("b-1"), title="", status="blocked")
        self.fake.beads[BeadId("tl-5")] = Bead(id=BeadId("tl-5"), title="stuck one", status="open")
        self.dash = make_dash(answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW), config=self.tmp.name, clock=lambda: NOW)
        repo = Path(self.tmp.name) / "demo"
        repo.mkdir()
        write_repos(self.dash.env.config.repos(), repo)
        self.asks = AskStore.at(self.dash.env.config)
        path = self.dash.env.config.ask(BeadId("b-1"))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(wire.dump(ASK)))
        log = manifest(self.dash.env.config, RUN, "tl-5", NOW - 5).log
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(typed("run_start", NOW - 5, run_id=RUN, bead="tl-5", worktree="")) + "\n")

    def post(self, verb, body):
        code, out = self.dash.writes.post(verb, body)
        self.assertEqual(code, 200)
        return wire.load(Result, out)

    def meta(self, bead, key):
        raw = self.fake.beads[bead].metadata.get(key)
        return json.loads(raw) if raw else {}

    def comments(self, bead):
        return [c.text for c in self.fake.comments(bead)]

    # answer

    def test_an_option_by_index_lands_as_the_asks_own_typed_answer(self):
        res = self.post("answer", {"project": "demo", "ask": "b-1-1", "kind": "answer", "option": 2})
        self.assertEqual(res, Result(ok=True))
        got = must(self.asks.get(BeadId("b-1")))
        given = must(got.answer)
        self.assertEqual((got.status, given.text, given.by), (AskStatus.ANSWERED, "Split the bead", "dash"))
        self.assertEqual(self.fake.beads[BeadId("b-1")].status, "open")  # the bead is opened for the loop
        self.assertTrue(any(c.startswith("Owner (tl) answer") for c in self.comments("b-1")))  # and the receipt is left

    def test_words_answer_and_an_answered_ask_is_amended_until_a_run_uses_it(self):
        self.assertTrue(self.post("answer", {"project": "demo", "ask": "b-1-1", "kind": "answer", "text": "go with A"}).ok)
        self.assertTrue(self.post("answer", {"project": "demo", "ask": "b-1-1", "kind": "answer", "text": "better"}).ok)
        self.assertEqual(must(must(self.asks.get(BeadId("b-1"))).answer).text, "better")
        self.asks.consume(BeadId("b-1"), NOW)
        res = self.post("answer", {"project": "demo", "ask": "b-1-1", "kind": "answer", "text": "too late"})
        self.assertEqual((res.ok, must(must(self.asks.get(BeadId("b-1"))).answer).text), (False, "better"))
        self.assertIn("already used", res.message)

    def test_refused_answers_change_nothing(self):
        before = (self.dash.env.config.ask(BeadId("b-1"))).read_text()
        for body, why in (({"ask": "b-1-1", "option": 9}, "not one of this ask"), ({"ask": "b-1-1", "option": -1}, "not one of this ask"),
                          ({"ask": "b-1-1", "text": "  "}, "Write an answer"), ({"ask": "nope-1", "text": "x"}, "no longer exists"),
                          ({"ask": "b-1-7", "text": "x"}, "asked again")):
            res = self.post("answer", {"project": "demo", "kind": "answer", **body})
            self.assertFalse(res.ok, body)
            self.assertIn(why, res.message, body)
        self.assertEqual(self.dash.env.config.ask(BeadId("b-1")).read_text(), before)

    # park, stop, note (backend item 7): the newest run's request file, the hold and the receipt through Intake

    def request(self):
        return requests.peek(self.dash.env.config, RUN)

    def test_park_holds_the_bead_and_asks_the_live_run_to_park(self):
        res = self.post("park", {"project": "demo", "bead": "tl-5"})
        self.assertEqual(res, Result(ok=True, message="Parks at the next step; the branch is kept."))
        got = must(self.request())
        self.assertEqual((got.park, got.stop, got.by, got.t), (True, False, "dash", NOW))
        self.assertEqual(self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold"), "dash")

    def test_stop_and_note_reach_the_same_request_file(self):
        self.assertTrue(self.post("note", {"project": "demo", "bead": "tl-5", "text": "use the blue one"}).ok)
        self.assertTrue(self.post("stop", {"project": "demo", "bead": "tl-5"}).ok)
        got = must(self.request())
        self.assertEqual((got.stop, [n.text for n in got.notes]), (True, ["use the blue one"]))
        self.assertTrue(any(c.startswith("Owner (tl) note: use the blue one") for c in self.comments("tl-5")))
        self.assertEqual(self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold"), "dash")

    def test_with_no_live_run_stop_is_refused_park_holds_and_a_note_is_a_hint(self):
        self.dash.env.clock = lambda: NOW + 3600
        self.dash.env.ports = answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW + 3600)
        manifest(self.dash.env.config, RUN, "tl-5", NOW - 5, state=RunState.LOST)  # the run's process is gone: recorded lost
        self.assertEqual(self.post("stop", {"project": "demo", "bead": "tl-5"}), Result(ok=False, message="no run of this bead is going"))
        self.assertIsNone(self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold"))
        self.assertTrue(self.post("park", {"project": "demo", "bead": "tl-5"}).ok)
        self.assertEqual(self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold"), "dash")
        self.assertIn("hint", self.post("note", {"project": "demo", "bead": "tl-5", "text": "later"}).message)
        self.assertEqual(self.fake.beads[BeadId("tl-5")].metadata.get("owner_hint"), "later")
        self.assertIsNone(self.request())

    def test_an_ask_back_joins_the_thread_and_leaves_the_ask_open(self):
        res = self.post("answer", {"project": "demo", "ask": "b-1-1", "kind": "ask_back", "text": " why two? "})
        self.assertEqual(res, Result(ok=True))
        got = must(self.asks.get(BeadId("b-1")))
        self.assertEqual((got.status, got.answer), (AskStatus.OPEN, None))
        self.assertEqual([(m.by, m.md, m.t) for m in got.thread], [("owner", "why two?", NOW)])
        for body, why in (({"ask": "b-1-1", "text": " "}, "write the question"), ({"ask": "b-1-7", "text": "x"}, "asked again")):
            res = self.post("answer", {"project": "demo", "kind": "ask_back", **body})
            self.assertEqual((res.ok, why in res.message), (False, True), body)
        self.assertEqual(len(must(self.asks.get(BeadId("b-1"))).thread), 1)

    # look

    def test_a_look_is_recorded_on_its_item(self):
        res = self.post("look", {"project": "demo", "bead": "tl-1#1", "verdict": "good"})
        self.assertEqual(res, Result(ok=True))
        self.assertEqual(self.fake.beads[BeadId("tl-look")].metadata["looks"][0]["status"], "good")
        res = self.post("look", {"project": "demo", "bead": "tl-1#1", "verdict": "redo", "note": "x"})
        self.assertFalse(res.ok)
        self.assertIn("Already answered", res.message)

    def test_a_redo_needs_its_note_and_files_the_follow_up_with_it(self):
        res = self.post("look", {"project": "demo", "bead": "tl-1#1", "verdict": "redo", "note": " "})
        self.assertEqual(res, Result(ok=False, message="Write what to change first."))
        self.assertEqual(self.fake.beads[BeadId("tl-look")].metadata["looks"][0]["status"], "open")
        self.assertTrue(self.post("look", {"project": "demo", "bead": "tl-1#1", "verdict": "redo", "note": "cut off"}).ok)
        made = self.fake.beads[self.fake.beads[BeadId("tl-look")].metadata["looks"][0]["redo_bead"]]
        self.assertIn("cut off", made.description)

    def test_a_look_that_bd_refuses_is_a_result_not_a_crash(self):
        self.fake.refuse = {"update-meta"}
        res = self.post("look", {"project": "demo", "bead": "tl-1#1", "verdict": "good"})
        self.assertFalse(res.ok)
        self.assertIn("bd refused", res.message)

    # cause, ack

    def test_a_cause_is_a_metadata_key_scoped_to_the_newest_run(self):
        self.assertEqual(self.post("cause", {"project": "demo", "bead": "tl-5", "cause": "flaky_test", "ask": None}), Result(ok=True))
        got = self.meta("tl-5", "owner_cause")
        self.assertEqual((got["scope"], got["cause"], got["by"], got["t"]), (RUN, "flaky_test", "dash", NOW))
        self.assertTrue(any("cause" in c and "flaky_test" in c for c in self.comments("tl-5")))
        self.post("cause", {"project": "demo", "bead": "tl-5", "cause": "environment", "ask": "b-1-1"})  # an ask's: scoped to the ask
        self.assertEqual(self.meta("tl-5", "owner_cause")["scope"], "b-1-1")

    def test_a_cause_outside_the_list_is_a_bad_body_and_a_bead_with_no_run_is_refused(self):
        code, _ = self.dash.writes.post("cause", {"project": "demo", "bead": "tl-5", "cause": "vibes"})
        self.assertEqual(code, 400)
        res = self.post("cause", {"project": "demo", "bead": "tl-9", "cause": "process"})
        self.assertFalse(res.ok)
        self.assertIsNone(self.fake.beads[BeadId("tl-5")].metadata.get("owner_cause"))

    def test_ack_sets_and_takes_back_the_seen_key(self):
        self.assertEqual(self.post("ack", {"project": "demo", "bead": "tl-5", "ack": True}), Result(ok=True))
        got = self.meta("tl-5", "owner_ack")
        self.assertEqual((got["scope"], got["by"]), (RUN, "dash"))
        self.assertEqual(self.post("ack", {"project": "demo", "bead": "tl-5", "ack": False}), Result(ok=True))
        self.assertEqual(self.meta("tl-5", "owner_ack"), {})
        self.assertFalse(self.post("ack", {"project": "demo", "bead": "tl-9", "ack": True}).ok)  # nothing to acknowledge

    def test_an_unknown_project_is_a_result_and_a_bd_that_is_down_too(self):
        res = self.post("ack", {"project": "nowhere", "bead": "tl-5", "ack": True})
        self.assertEqual(res, Result(ok=False, message="That project is not registered."))
        def no_bd(repo):
            raise OSError(2, "bd is not installed")
        self.dash.env.ports = answering(no_bd, self.tmp.name)
        res = self.post("ack", {"project": "demo", "bead": "tl-5", "ack": True})
        self.assertFalse(res.ok)
        self.assertIn("cannot run bd", res.message)

    # the wire

    def test_unknown_verb_is_404_and_a_malformed_body_is_400(self):
        self.assertEqual(self.dash.writes.post("explode", {})[0], 404)
        for verb, body in (("ack", {"project": "demo", "bead": "tl-5"}), ("ack", {"project": "demo", "bead": "t", "ack": True, "x": 1}),
                           ("look", []), ("look", {"project": "demo", "bead": "x", "verdict": "maybe"}), ("answer", None)):
            self.assertEqual(self.dash.writes.post(verb, body)[0], 400, (verb, body))

if __name__ == "__main__":
    unittest.main()
