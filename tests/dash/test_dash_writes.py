"""POST /api/<verb>: answer, look, cause and ack through the real Intake over a bd in memory; the Result shape; the refused cases."""
import json
import sys
from pathlib import Path
from unittest import mock

from support.case import Case
from support.tmpdir import TemporaryDirectory

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
from taskloop.contracts import factorydb, wire
from taskloop.contracts.askstore import AskStore
from taskloop.contracts.bead import Bead
from taskloop.contracts.dash import Result
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId, loop_key
from taskloop.contracts.lookrows import LookRows
from taskloop.contracts.run import RunState

NOW = 1_800_000_000.0
ASK = MOCKS["lifesim-22b3"].replace(bead="b-1", id="b-1-1")
RUN = "tl-5-20261026-100000"


class Writes(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = world("open")
        self.fake.beads[BeadId("b-1")] = Bead(id=BeadId("b-1"), title="", status="blocked")
        self.fake.beads[BeadId("tl-5")] = Bead(id=BeadId("tl-5"), title="stuck one", status="open")
        self.dash = make_dash(answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW), config=self.tmp.name, clock=lambda: NOW)
        repo = Path(self.tmp.name) / "demo"
        repo.mkdir()
        self.repo = repo
        write_repos(self.dash.env.config.repos(), repo)
        self.asks = AskStore.at(self.dash.env.config)
        self.asks.put(ASK)
        log = manifest(self.dash.env.config, RUN, "tl-5", NOW - 5, repo=str(repo)).log
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps(typed("run_start", NOW - 5, run_id=RUN, bead="tl-5", worktree="")) + "\n")

    def post(self, verb, body):
        code, out = self.dash.writes.post(verb, body)
        assert code == 200
        return wire.load(Result, out)

    def look_items(self):
        return LookRows(self.dash.env.config).items("tl-look") or []

    def meta(self, bead, key):
        raw = self.fake.beads[bead].metadata.get(key)
        return json.loads(raw) if raw else {}

    def comments(self, bead):
        return [c.text for c in self.fake.comments(bead)]

    # answer

    def test_an_option_by_index_lands_as_the_asks_own_typed_answer(self):
        res = self.post("answer", {"project": loop_key(self.repo), "ask": "b-1-1", "kind": "answer", "option": 2})
        assert res == Result(ok=True)
        got = must(self.asks.get(BeadId("b-1")))
        given = must(got.answer)
        assert (got.status, given.text, given.by) == (AskStatus.ANSWERED, "Split the bead", "dash")
        assert self.fake.beads[BeadId("b-1")].status == "open"  # the bead is opened for the loop
        assert any(c.startswith("Owner (tl) answer") for c in self.comments("b-1"))  # and the receipt is left

    def test_words_answer_and_an_answered_ask_is_amended_until_a_run_uses_it(self):
        assert self.post("answer", {"project": loop_key(self.repo), "ask": "b-1-1", "kind": "answer", "text": "go with A"}).ok
        assert self.post("answer", {"project": loop_key(self.repo), "ask": "b-1-1", "kind": "answer", "text": "better"}).ok
        assert must(must(self.asks.get(BeadId("b-1"))).answer).text == "better"
        self.asks.consume(BeadId("b-1"), NOW)
        res = self.post("answer", {"project": loop_key(self.repo), "ask": "b-1-1", "kind": "answer", "text": "too late"})
        assert (res.ok, must(must(self.asks.get(BeadId("b-1"))).answer).text) == (False, "better")
        assert "already used" in res.message

    def test_refused_answers_change_nothing(self):
        before = self.asks.get(BeadId("b-1"))
        for body, why in (({"ask": "b-1-1", "option": 9}, "not one of this ask"), ({"ask": "b-1-1", "option": -1}, "not one of this ask"),
                          ({"ask": "b-1-1", "text": "  "}, "Write an answer"), ({"ask": "nope-1", "text": "x"}, "no longer exists"),
                          ({"ask": "b-1-7", "text": "x"}, "asked again")):
            res = self.post("answer", {"project": loop_key(self.repo), "kind": "answer", **body})
            assert not res.ok, body
            assert why in res.message, body
        assert self.asks.get(BeadId("b-1")) == before

    # park, stop, note (backend item 7): the newest run's request file, the hold and the receipt through Intake

    def request(self):
        return requests.peek(self.dash.env.config, RUN)

    def test_park_holds_the_bead_and_asks_the_live_run_to_park(self):
        res = self.post("park", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN})
        assert res == Result(ok=True, message="Parks at the next step; the branch is kept.")
        got = must(self.request())
        assert (got.park, got.stop, got.by, got.t) == (True, False, "dash", NOW)
        assert self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold") == "dash"

    def test_stop_and_note_reach_the_same_request_file(self):
        assert self.post("note", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "text": "use the blue one"}).ok
        assert self.post("stop", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN}).ok
        got = must(self.request())
        assert (got.stop, [n.text for n in got.notes]) == (True, ["use the blue one"])
        assert any(c.startswith("Owner (tl) note: use the blue one") for c in self.comments("tl-5"))
        assert self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold") == "dash"

    def test_commands_for_an_ended_run_are_refused_without_writes(self):
        self.dash.env.clock = lambda: NOW + 3600
        self.dash.env.ports = answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW + 3600)
        manifest(self.dash.env.config, RUN, "tl-5", NOW - 5, repo=str(self.repo), state=RunState.LOST)
        res = self.post("stop", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN})
        assert res == Result(ok=False, message="no run of this bead is going")
        assert self.fake.beads[BeadId("tl-5")].metadata.get("owner_hold") is None
        for verb, fields in (("park", {}), ("note", {"text": "later"}), ("ack", {"ack": True}), ("cause", {"cause": "process"})):
            res = self.post(verb, {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, **fields})
            assert not res.ok
            assert res.message == "no run of this bead is going"
        assert not self.fake.beads[BeadId("tl-5")].metadata
        assert self.request() is None

    def test_an_ask_back_joins_the_thread_and_leaves_the_ask_open(self):
        res = self.post("answer", {"project": loop_key(self.repo), "ask": "b-1-1", "kind": "ask_back", "text": " why two? "})
        assert res == Result(ok=True)
        got = must(self.asks.get(BeadId("b-1")))
        assert (got.status, got.answer) == (AskStatus.OPEN, None)
        assert [(m.by, m.md, m.t) for m in got.thread] == [("owner", "why two?", NOW)]
        for body, why in (({"ask": "b-1-1", "text": " "}, "write the question"), ({"ask": "b-1-7", "text": "x"}, "asked again")):
            res = self.post("answer", {"project": loop_key(self.repo), "kind": "ask_back", **body})
            assert (res.ok, why in res.message) == (False, True), body
        assert len(must(self.asks.get(BeadId("b-1"))).thread) == 1

    # look

    def test_a_look_is_recorded_on_its_item(self):
        res = self.post("look", {"project": loop_key(self.repo), "bead": "tl-1#1", "verdict": "good"})
        assert res == Result(ok=True)
        assert self.look_items()[0]["status"] == "good"
        res = self.post("look", {"project": loop_key(self.repo), "bead": "tl-1#1", "verdict": "redo", "note": "x"})
        assert not res.ok
        assert "Already answered" in res.message

    def test_a_redo_needs_its_note_and_files_the_follow_up_with_it(self):
        res = self.post("look", {"project": loop_key(self.repo), "bead": "tl-1#1", "verdict": "redo", "note": " "})
        assert res == Result(ok=False, message="Write what to change first.")
        assert self.look_items() == []  # nothing was answered, so no row
        assert self.post("look", {"project": loop_key(self.repo), "bead": "tl-1#1", "verdict": "redo", "note": "cut off"}).ok
        made = self.fake.beads[self.look_items()[0]["redo_bead"]]
        assert "cut off" in made.description

    def test_a_look_whose_row_cannot_be_saved_is_a_result_not_a_crash(self):
        with mock.patch.object(LookRows, "_swap", side_effect=factorydb.DatabaseError("disk full")):
            res = self.post("look", {"project": loop_key(self.repo), "bead": "tl-1#1", "verdict": "good"})
        assert not res.ok
        assert "not saved" in res.message

    # cause, ack

    def test_a_cause_is_a_metadata_key_scoped_to_the_newest_run(self):
        res = self.post("cause", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "cause": "flaky_test", "ask": None})
        assert res == Result(ok=True)
        got = self.meta("tl-5", "owner_cause")
        assert (got["scope"], got["cause"], got["by"], got["t"]) == (RUN, "flaky_test", "dash", NOW)
        assert any("cause" in c and "flaky_test" in c for c in self.comments("tl-5"))
        res = self.post("cause", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN,
                                  "cause": "environment", "ask": "b-1-1"})
        assert not res.ok  # a different bead's ask cannot change this run's cause
        assert self.meta("tl-5", "owner_cause")["scope"] == RUN

    def test_a_cause_outside_the_list_is_a_bad_body_and_a_bead_with_no_run_is_refused(self):
        code, _ = self.dash.writes.post("cause", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "cause": "vibes"})
        assert code == 400
        res = self.post("cause", {"project": loop_key(self.repo), "bead": "tl-9", "run": RUN, "cause": "process"})
        assert not res.ok
        assert self.fake.beads[BeadId("tl-5")].metadata.get("owner_cause") is None

    def test_ack_sets_and_takes_back_the_seen_key(self):
        assert self.post("ack", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "ack": True}) == Result(ok=True)
        got = self.meta("tl-5", "owner_ack")
        assert (got["scope"], got["by"]) == (RUN, "dash")
        assert self.post("ack", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "ack": False}) == Result(ok=True)
        assert self.meta("tl-5", "owner_ack") == {}
        assert not self.post("ack", {"project": loop_key(self.repo), "bead": "tl-9", "run": RUN, "ack": True}).ok

    def test_an_unknown_project_is_a_result_and_a_bd_that_is_down_too(self):
        res = self.post("ack", {"project": "nowhere", "bead": "tl-5", "run": RUN, "ack": True})
        assert res == Result(ok=False, message="That project is not registered.")
        def no_bd(repo):
            raise OSError(2, "bd is not installed")
        self.dash.env.ports = answering(no_bd, self.tmp.name)
        res = self.post("ack", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "ack": True})
        assert not res.ok
        assert "cannot run bd" in res.message

    # the wire

    def test_unknown_verb_is_404_and_a_malformed_body_is_400(self):
        assert self.dash.writes.post("explode", {})[0] == 404
        for verb, body in (("ack", {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN}),
                           ("ack", {"project": loop_key(self.repo), "bead": "t", "ack": True, "x": 1}),
                           ("look", []), ("look", {"project": loop_key(self.repo), "bead": "x", "verdict": "maybe"}), ("answer", None)):
            assert self.dash.writes.post(verb, body)[0] == 400, (verb, body)


class Receipts(Writes):
    def body(self, key, **more):
        return {"project": loop_key(self.repo), "bead": "tl-5", "run": RUN, "key": key, **more}

    def test_a_retried_note_with_the_same_key_acts_once_and_gets_the_first_answer(self):
        first = self.post("note", self.body("k-1", text="use the blue one"))
        again = self.post("note", self.body("k-1", text="use the blue one"))
        assert first == again == Result(ok=True, message=first.message, receipt="accepted")
        assert [n.text for n in must(self.request()).notes] == ["use the blue one"]
        assert sum(c.startswith("Owner (tl) note") for c in self.comments("tl-5")) == 1

    def test_a_refusal_at_a_terminal_race_is_kept_as_a_receipt_and_survives_a_restart(self):
        self.dash.env.clock = lambda: NOW + 3600
        self.dash.env.ports = answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW + 3600)
        manifest(self.dash.env.config, RUN, "tl-5", NOW - 5, repo=str(self.repo), state=RunState.LOST)
        refused = self.post("stop", self.body("k-2"))
        assert (refused.ok, refused.receipt) == (False, "refused")
        restarted = make_dash(answering(lambda repo: self.fake, self.tmp.name, clock=lambda: NOW), config=self.tmp.name, clock=lambda: NOW)
        code, out = restarted.writes.post("stop", self.body("k-2"))
        assert (code, wire.load(Result, out)) == (200, refused)

    def test_a_key_reused_for_another_command_is_refused_and_a_command_without_a_key_has_no_receipt(self):
        assert self.post("park", self.body("k-3")).ok
        other = self.post("stop", self.body("k-3"))
        assert (other.ok, other.receipt) == (False, "refused")
        assert not must(self.request()).stop
        assert self.post("note", {**self.body("", text="x")}).receipt == ""
