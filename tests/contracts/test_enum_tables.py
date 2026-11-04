"""Previously implicit enum cases have explicit behavior in constant tables."""

from support.case import Case

from taskloop.contracts.enums import Step
from taskloop.contracts.kinds import ASK_NAME, ASKS, Kind
from taskloop.contracts.runlife import silent_limit


class ContractTables(Case):
    def test_non_ask_kinds_have_no_ask_name(self):
        assert set(ASK_NAME) == set(Kind)
        for kind in Kind:
            assert ASK_NAME[kind] == (kind.value.removeprefix("ask_") if kind in ASKS else "")

    def test_undrawn_steps_keep_the_thirty_minute_silence_limit(self):
        for step in (Step.RESET, Step.CLOSE, Step.REFLECT):
            assert silent_limit(step) == 1800
