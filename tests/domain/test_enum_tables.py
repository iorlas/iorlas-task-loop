"""New explicit enum cases preserve engine refusal and delegate retry authority."""

from tlkernel import lanepauses as pauses
from tlkernel.askenums import AskClass
from tlkernel.asklint import INFRA, KIND_OF
from tlkernel.pausereasons import Reason
from tltestkit.case import Case


class PolicyTables(Case):
    def test_engine_trouble_has_no_owner_ask_kind(self):
        assert set(KIND_OF) == set(AskClass)
        for classification in INFRA:
            assert KIND_OF[classification] is None

    def test_every_reason_explicitly_defines_backoff_and_override(self):
        assert set(pauses.BACKOFF) == set(Reason)
        assert set(pauses.OVERRIDES) == set(Reason)
        for reason in Reason:
            if (pauses.BACKOFF[reason] is None and pauses.OVERRIDES[reason] is None
                    and ("delegate", reason) not in pauses.TABLE):
                with self.subTest(reason=reason):
                    assert pauses.rule(reason, "delegate", "transient") == pauses.PauseRule("transient", 60, 3600, 3)
                    assert pauses.rule(reason, "delegate", "needs_owner") == pauses.PauseRule("needs_owner")
