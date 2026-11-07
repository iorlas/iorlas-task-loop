"""Missing-setup asks receive one typed engine retry per bead and release."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.memstores import fake_stores
from support.narrow import must

from taskloop.app.asks import raiser, setup_retry
from taskloop.app.run.ask_flow import AskFlow
from taskloop.app.wire import asks as wire_asks
from taskloop.domain.asks import specs
from tlkernel.ask import AskAnswer
from tlkernel.askstore import HAD_PICK
from tlkernel.bead import Bead
from tlkernel.config import load
from tlkernel.enums import AskKind, AskStatus
from tlkernel.identity import Identity
from tlkernel.ids import BeadId

BEAD = BeadId("t-1")
WHY = "failed: the configured check `unity` needs something this tree lacks: client/ is not set up"


class SetupRetry(Case):
    def setup_method(self):
        self.asks = fake_stores().asks
        self.store = FakeBeads()
        self.store.beads[BEAD] = Bead(id=BEAD, title="T", status="blocked", labels=["needs-info"], metadata={HAD_PICK: "auto"})
        self.cfg = load({"engine": {"pick_label": "auto", "needs_info_label": "needs-info", "checks": [
            {"id": "unity", "argv": ["unity-check"], "run": "gate", "run_in": "slot"},
        ]}}).engine
        self.file()

    def file(self, why=WHY, stuck=False):
        at = raiser.Asking(bead=BEAD, run="r", brief_hash="brief", repo="/repo", title="T", now=1, why=why)
        spec = specs.no_progress("checks", 2, why) if stuck else specs.missing_criteria()
        return must(raiser.raise_ask(self.asks, spec, at)[0])

    def retry(self, version="1.0", starting=False):
        return setup_retry.retry_setup(self.asks, self.store, BEAD, version, 2, self.cfg, starting=starting)

    def test_slot_gate_configuration_answers_and_restores_the_queue(self):
        assert self.retry()
        ask = must(self.asks.get(BEAD))
        answer = must(ask.answer)
        assert (ask.status, answer.action, answer.text, answer.by) == (AskStatus.ANSWERED, "rerun", "retry", "engine:1.0")
        bead = self.store.beads[BEAD]
        assert (bead.status, bead.labels) == ("open", ["auto"])
        assert HAD_PICK not in bead.metadata
        assert raiser.check(self.asks, BEAD, "brief", False, 3)[0] == "answer"

    def test_replacing_an_ask_and_restarting_does_not_reset_the_release_budget(self):
        assert self.retry()
        self.file()
        assert not self.retry(starting=True)
        assert self.retry(version="1.1", starting=True)
        self.file()
        assert not self.retry(version="1.0", starting=True)
        assert not self.retry(version="1.1", starting=True)

    def test_engine_start_retries_even_before_the_profile_is_changed_to_slot(self):
        self.cfg = self.cfg.replace(checks=[self.cfg.checks[0].replace(run_in="clean")])
        assert not self.retry()
        assert self.retry(starting=True)

    def test_engine_ask_flow_answers_and_consumes_the_setup_ask(self):
        host = SimpleNamespace(stores=SimpleNamespace(asks=self.asks), store=self.store, bead=BEAD, cfg=self.cfg,
                               dry=False, brief_hash="brief", fresh=False, briefs=mock.Mock(), log=mock.Mock())
        with mock.patch("taskloop.app.run.ask_flow.ident.plugin_version", return_value="1.0"):
            AskFlow(host).check()
        assert host.answered.answer.text == "retry"
        assert must(self.asks.get(BEAD)).consumed is not None
        host.briefs.export.assert_called_once()

    def test_unrelated_reasons_and_other_failing_checks_are_left_for_the_owner(self):
        for why in ("client/ is unavailable", WHY.replace("`unity`", "`unity-other`")):
            with self.subTest(why=why):
                self.file(why)
                assert not self.retry()
                assert must(self.asks.get(BEAD)).answer is None
        self.file("client/ is unavailable")
        assert not self.retry(starting=True)

    def test_stage_only_slot_check_does_not_trigger_loop_recovery(self):
        self.cfg = self.cfg.replace(checks=[self.cfg.checks[0].replace(run="stage")])
        assert not self.retry()

    def test_owner_answer_consumed_and_closed_asks_are_preserved(self):
        for changes in ({"answer": AskAnswer(action="text", text="wait", by="owner")},
                        {"consumed": 2}, {"status": AskStatus.CLOSED}):
            with self.subTest(changes=changes):
                ask = self.file().replace(**changes)
                self.asks.put(ask)
                assert not self.retry(starting=True)
                assert self.asks.get(BEAD) == ask

    def test_parked_ask_wakes_without_granting_a_pick_label_it_never_had(self):
        self.store.beads[BEAD].metadata.clear()
        ask = must(self.asks.get(BEAD))
        self.asks.park(BEAD, ask.id)
        assert self.retry()
        assert self.store.beads[BEAD].labels == []

    def test_bad_budget_and_unknown_version_fail_closed(self):
        for value in ("broken", "{}", "[1]", '["1.0"]'):
            with self.subTest(value=value):
                self.store.beads[BEAD].metadata[setup_retry.RETRIED] = value
                assert not self.retry(starting=True)
        self.store.beads[BEAD].metadata.pop(setup_retry.RETRIED)
        assert not self.retry(version="", starting=True)

    def test_loop_sweep_requeues_only_asks_of_its_own_repository(self):
        ask = self.file(stuck=True)
        assert ask.kind == AskKind.STUCK
        self.asks.park(BEAD, ask.id)
        who = Identity(actor="engine", home="/unused")
        with (mock.patch.object(wire_asks, "store", return_value=self.asks),
              mock.patch.object(wire_asks, "bd_store", return_value=self.store),
              mock.patch.object(wire_asks, "sweep"),
              mock.patch.object(wire_asks, "now", return_value=2),
              mock.patch.object(wire_asks.ident, "plugin_version", return_value="1.0"),
              mock.patch.object(wire_asks.sweeps, "reask_orphans"),
              mock.patch.object(wire_asks.sweeps, "shout")):
            wire_asks.sweep_asks(who, who.config, cfg=self.cfg, repo="/other")
            assert must(self.asks.get(BEAD)).answer is None
            wire_asks.sweep_asks(who, who.config, cfg=self.cfg, repo="/repo")
        assert must(must(self.asks.get(BEAD)).answer).text == "retry"
        assert self.store.beads[BEAD].status == "open"
        assert self.store.beads[BEAD].labels == ["auto"]
        assert not self.retry()
