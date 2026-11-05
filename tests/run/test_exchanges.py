"""REPLAYGOLDEN: every recorded exchange (tests/fixtures/exchanges, see support/exchanges.py) replays through the fake route: the parser
takes the recorded answer and the engine still builds the recorded input. UPDATE_GOLDEN=1 rewrites the input.txt files."""
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import exchanges as ex

from taskloop.app.plan import prompt as pp
from taskloop.domain.prompts import review as rp
from taskloop.domain.prompts import write as wp

LIMIT_S = 6.0  # replays every recorded exchange through the engine: 2.0-3.4 s of CPU in the release container with 7 workers
ALL = ex.cases()


class Recorded(te.EngineTest):
    def test_there_is_one_exchange_per_role(self):
        assert {e.role for e in ALL} == {"planner", "writer", "reviewer"}

    def test_every_case_says_what_is_real_and_what_is_not(self):
        for e in ALL:
            with self.subTest(e.name):
                assert e.meta["answer"] in ("real", "synthetic")
                assert e.meta["input"] in ("real", "synthetic")
                assert e.meta["source"]

    def test_the_cases_replay(self):
        for e in ALL:
            with self.subTest(e.name):
                self.setup_method()  # a fresh world per case: one engine per test
                try:
                    ex.replay(self, e)
                finally:
                    self.teardown_method()


class Breaks(te.EngineTest):
    """The goldens do fail: a changed prompt or answer is a red test, not a silent pass (and never rewrites a golden)."""

    def setup_method(self):
        super().setup_method()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("UPDATE_GOLDEN", None)

    def test_a_changed_prompt_template_fails_its_golden(self):
        by = {e.role: e for e in ALL}
        for role, mod, name in (("planner", pp, "PLAN_PROMPT"), ("writer", wp, "WRITE_PROMPT"), ("reviewer", rp, "REVIEW_PROMPT")):
            with self.subTest(role):
                self.setup_method()
                try:
                    with mock.patch.object(mod, name, getattr(mod, name) + "\nExtra line.\n"), pytest.raises(AssertionError):
                        ex.replay(self, by[role])
                finally:
                    self.teardown_method()

    def test_an_answer_the_parser_rejects_fails_its_golden(self):
        for e in ALL:
            with self.subTest(e.name):
                gone = {k: v for k, v in e.answer.items() if k not in {"summary", "findings"}}
                broken = ex.Exchange(e.role, e.case, e.dir, e.meta, e.bead, gone, e.plan)
                with pytest.raises(AssertionError):
                    ex.replay(self, broken)
