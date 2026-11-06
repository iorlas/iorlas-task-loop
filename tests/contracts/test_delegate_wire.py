"""The typed delegate answer (contract 4) agrees with the adapter that reads it and the policy tables (lane policy)."""
import sys
from pathlib import Path
from typing import get_args, get_type_hints

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from contracts import samples as S
from taskloop.adapters import delegate as dl
from taskloop.adapters import delegate_wire
from taskloop.contracts import delegate, wire
from taskloop.domain.lanes import policy as lp


class Contract4(Case):
    def test_the_contract_number_is_the_one_the_engine_speaks(self):
        assert get_args(get_type_hints(delegate.DelegateResult)["contract"]) == (dl.CONTRACT,)

    def test_the_stop_facts_vocabulary_is_lane_policys(self):
        hints = get_type_hints(delegate.StopFacts)
        assert set(get_args(hints["scope"])) == set(lp.SCOPES)
        assert set(get_args(hints["permanence"])) == set(lp.PERMANENCES)
        assert set(get_args(get_type_hints(delegate.Retry)["kind"])) == set(lp.RETRY_KINDS)

    def test_no_removed_field_is_left(self):
        fields = set(get_type_hints(delegate.DelegateResult))
        assert not fields & {"status", "next", "reason", "retry_after", "v"}

    def test_the_sample_answer_is_read_by_the_adapter_into_the_same_result(self):
        body = wire.dump(S.other(delegate.DelegateResult))
        assert "v" not in body
        assert wire.load(delegate.DelegateResult, body) == S.other(delegate.DelegateResult)
        r = delegate_wire.result_of(body)
        st, facts = r.stop, S.other(delegate.DelegateResult).stop
        assert st == facts
        assert (r.worker, r.exit_code, r.first_error) == (S.other(delegate.DelegateResult).worker, -15, "429 rate limited")

    def test_a_done_answer_has_a_null_stop(self):
        body = {**wire.dump(S.other(delegate.DelegateResult)), "stop": None}
        assert delegate_wire.result_of(body).stop is None
        assert wire.load(delegate.DelegateResult, body).stop is None
