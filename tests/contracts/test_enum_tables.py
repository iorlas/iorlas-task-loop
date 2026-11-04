"""Previously implicit enum cases have explicit behavior in constant tables."""
import unittest

from taskloop.contracts.enums import Step
from taskloop.contracts.kinds import ASK_NAME, ASKS, Kind
from taskloop.contracts.runlife import silent_limit


class ContractTables(unittest.TestCase):
    def test_non_ask_kinds_have_no_ask_name(self):
        self.assertEqual(set(ASK_NAME), set(Kind))
        for kind in Kind:
            self.assertEqual(ASK_NAME[kind], kind.value.removeprefix("ask_") if kind in ASKS else "")

    def test_undrawn_steps_keep_the_thirty_minute_silence_limit(self):
        for step in (Step.RESET, Step.CLOSE, Step.REFLECT):
            self.assertEqual(silent_limit(step), 1800)
