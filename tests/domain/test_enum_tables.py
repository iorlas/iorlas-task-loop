"""New explicit enum cases preserve engine refusal and delegate retry authority."""
import unittest

from taskloop.contracts.enums import AskClass
from taskloop.domain.asks.lint import INFRA, KIND_OF
from taskloop.domain.lanes import pauses
from taskloop.domain.lanes.pause_reasons import Reason


class PolicyTables(unittest.TestCase):
    def test_engine_trouble_has_no_owner_ask_kind(self):
        self.assertEqual(set(KIND_OF), set(AskClass))
        for classification in INFRA:
            self.assertIsNone(KIND_OF[classification])

    def test_every_reason_explicitly_defines_backoff_and_override(self):
        self.assertEqual(set(pauses.BACKOFF), set(Reason))
        self.assertEqual(set(pauses.OVERRIDES), set(Reason))
        for reason in Reason:
            if (pauses.BACKOFF[reason] is None and pauses.OVERRIDES[reason] is None
                    and ("delegate", reason) not in pauses.TABLE):
                with self.subTest(reason=reason):
                    self.assertEqual(pauses.rule(reason, "delegate", "transient"), pauses.PauseRule("transient", 60, 3600, 3))
                    self.assertEqual(pauses.rule(reason, "delegate", "needs_owner"), pauses.PauseRule("needs_owner"))
