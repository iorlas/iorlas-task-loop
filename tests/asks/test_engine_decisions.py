"""The engine side of asks and decisions: the planner reads the repo's decisions and cites them, a reversible plan question becomes a
soft ask the run goes on past, an agent's declared cause reaches the ask, and a repeat is matched when it is raised."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest
from support.narrow import must

from taskloop.adapters import ident
from taskloop.app.asks import intake
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import SimilarRef
from taskloop.contracts.dash import OwnerCause
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ledger import Adr
from taskloop.contracts.paths import ConfigDir
from taskloop.domain.asks import similar, specs

OPTS = [{"label": "Push", "cost": "shared", "answer": "push", "recommended": True},
        {"label": "Hold", "cost": "slow", "answer": "hold", "recommended": False}]
PUSH = "Push the rewritten history to main?"
IRREVERSIBLE = dict(PLAN, question=PUSH, irreversible="push_shared", options=OPTS)


class EngineDecisions(EngineTest):
    def repo(self) -> str:
        """The repo path as the engine names it (the parent of the git common dir)."""
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=self.wt, capture_output=True,
                                text=True, check=True).stdout.strip()
        return str(Path(common).parent)

    def adrs(self) -> AdrStore:
        return AdrStore.at(ConfigDir(ident.config_dir()), self.repo())

    def decide(self, text: str, key: str = "") -> Adr:
        return self.adrs().add(Adr(id="", n=0, repo=self.repo(), text=text, question="q?", answer="a", ask="x-1", bead="x", key=key, t=1.0))

    def test_the_planner_reads_the_decisions_in_force_and_the_ones_it_cites_are_counted(self):
        first = self.decide("Saves stay in format v1.")
        self.decide("Money moves weekly.")
        rc, s = self.run_engine({"plan": [dict(PLAN, cited=[first.id, "ADR-77"])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("Decisions in force for this repo", s.prompts[0])
        self.assertIn("ADR-1: Saves stay in format v1.", s.prompts[0])
        self.assertIn("ADR-2: Money moves weekly.", s.prompts[0])
        self.assertIn("`cited`", s.prompts[0])
        uses = self.adrs().uses()
        self.assertEqual([(u.adr, u.bead) for u in uses], [("ADR-1", "t-1")])  # the unknown id is dropped, not counted
        self.assertEqual(self.adrs().reuses()["ADR-1"][0], 1)
        self.assertIn("do not exist: ADR-77", self.eng.log_path.read_text())

    def test_a_pruned_decision_is_no_longer_read_cited_or_matched(self):
        old = self.decide("Saves stay in format v1.")
        self.decide("Money moves weekly.")
        self.assertEqual(self.adrs().retire(old.id, "denis", 5.0), "")
        rc, s = self.run_engine({"plan": [dict(PLAN, cited=[old.id, "ADR-2"])], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("Saves stay in format v1.", s.prompts[0])
        self.assertIn("ADR-2: Money moves weekly.", s.prompts[0])
        self.assertEqual([u.adr for u in self.adrs().uses()], ["ADR-2"])

    def test_a_repo_with_no_decisions_adds_nothing_to_the_prompt(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertNotIn("Decisions in force", s.prompts[0])
        self.assertEqual(self.adrs().uses(), [])

    def test_a_reversible_plan_question_is_a_soft_ask_and_the_run_goes_on_with_its_default(self):
        q = dict(PLAN, question="Which file do I follow?", options=OPTS, owner_cause="requirement")
        rc, _s = self.run_engine({"plan": [q], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        ask = must(self.asks().get("t-1"))
        # the run landed on it, so the ask is closed
        self.assertEqual((ask.blocking, ask.status, ask.owner_cause, ask.cause_by),
                         (False, AskStatus.CLOSED, OwnerCause.REQUIREMENT, "agent"))
        self.assertIn("planned on the bead text and the repo", ask.default)
        self.assertEqual([r.event for r in self.asks().history(ask.id)], ["raise", "close"])
        self.assertNotIn("t-1", [c[2] for c in self.bd_calls if c[:2] == ("labels", "remove")])  # nothing left the pick queue

    def test_an_irreversible_question_is_a_blocking_ask_with_the_cause_the_agent_declared(self):
        rc, _s = self.run_engine({"plan": [dict(IRREVERSIBLE, owner_cause="decision")]})
        self.assertEqual(rc, 2)
        ask = must(self.asks().get("t-1"))
        self.assertEqual((ask.blocking, ask.default, ask.owner_cause, ask.status), (True, "", OwnerCause.DECISION, AskStatus.OPEN))

    def test_a_cause_outside_the_list_is_unknown_and_none_is_unknown(self):
        self.run_engine({"plan": [dict(IRREVERSIBLE, owner_cause="unknown")]})
        self.assertEqual(must(self.asks().get("t-1")).owner_cause, OwnerCause.UNKNOWN)

    def test_a_repeat_ask_names_the_decision_and_the_past_answer_it_matches(self):
        key = similar.key_of(specs.open_question(PUSH, None).ask_class, PUSH)
        adr = self.decide("History is never pushed to main.", key)
        rc, _s = self.run_engine({"plan": [IRREVERSIBLE]})
        self.assertEqual(rc, 2)
        first = must(self.asks().get("t-1"))
        self.assertEqual((first.key, first.similar), (key, [SimilarRef(kind="adr", id=adr.id)]))
        intake.Intake(self.asks(), self.store, lambda: 5.0, "denis").answer(BeadId("t-1"), "text", "hold")
        self.assertEqual(json.loads((ident.config_dir() / "ask-ledger.jsonl").read_text().splitlines()[0])["event"], "raise")
