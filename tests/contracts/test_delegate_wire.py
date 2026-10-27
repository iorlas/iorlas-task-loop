"""The typed delegate answer (contract 3) agrees with the engine's reader (delegate_link) and the policy tables (lane_policy)."""
import sys
import unittest
from pathlib import Path
from typing import get_args, get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); import support.paths  # noqa: E402,F401
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "task-loop"))
import delegate_link as dl  # noqa: E402
import lane_policy as lp  # noqa: E402
from taskloop.contracts import codec, delegate  # noqa: E402

from contracts import samples as S  # noqa: E402


class Contract3(unittest.TestCase):
    def test_the_contract_number_is_the_one_the_engine_speaks(self):
        self.assertEqual(get_args(get_type_hints(delegate.DelegateResult)["contract"]), (dl.CONTRACT,))

    def test_the_stop_facts_vocabulary_is_lane_policys(self):
        hints = get_type_hints(delegate.StopFacts)
        self.assertEqual(set(get_args(hints["scope"])), set(lp.SCOPES))
        self.assertEqual(set(get_args(hints["permanence"])), set(lp.PERMANENCES))
        self.assertEqual(set(get_args(get_type_hints(delegate.Retry)["kind"])), set(lp.RETRY_KINDS))

    def test_no_removed_field_is_left(self):
        fields = set(get_type_hints(delegate.DelegateResult))
        self.assertFalse(fields & {"status", "next", "reason", "retry_after", "v"})

    def test_the_sample_answer_is_read_by_delegate_link_into_the_same_stop(self):
        wire = codec.to_json(S.OTHERS["DelegateResult"])
        self.assertNotIn("v", wire)
        self.assertEqual(codec.from_json(delegate.DelegateResult, wire), S.OTHERS["DelegateResult"])
        r = dl.answer_of({}, wire)
        st, facts = r.stop, S.OTHERS["DelegateResult"].stop
        self.assertEqual((st.scope, st.permanence, st.retry_kind, st.retry_at, st.reason, st.resumable, st.partial, st.ref),
                         (facts.scope, facts.permanence, facts.retry.kind, facts.retry.at, facts.reason, facts.resumable, facts.partial, facts.ref))

    def test_a_done_answer_has_a_null_stop(self):
        wire = {**codec.to_json(S.OTHERS["DelegateResult"]), "stop": None}
        self.assertIsNone(dl.answer_of({}, wire).stop)
        self.assertIsNone(codec.from_json(delegate.DelegateResult, wire).stop)

    def test_the_run_argv_carries_the_flags_delegate_link_builds(self):
        class Req:
            role, cwd, parent, task, title, timeout_s, resume, authored_by, call_id = "worker", "/w", "p", "t", "T", 0, "", "", ""
        req = S.OTHERS["RunRequest"]
        ours = delegate.RunRequest(role="worker", brief_path="b", cwd="/w", schema_path="s", parent="p", task="t", title="T").to_argv("py", "r")
        theirs = dl.argv_of(type("R", (), {"route": "r"})(), Req, "b", "s")
        self.assertEqual([x for x in ours if x != "py"], [x for x in theirs if x != sys.executable])
        self.assertIsNotNone(req)


if __name__ == "__main__":
    unittest.main()
