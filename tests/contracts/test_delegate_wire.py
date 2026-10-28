"""The typed delegate answer (contract 3) agrees with the adapter that reads it and the policy tables (lane policy)."""
import sys
import unittest
from pathlib import Path
from typing import get_args, get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "task-loop"))
from taskloop.adapters import delegate as dl, delegate_wire  # noqa: E402
from taskloop.domain.lanes import policy as lp  # noqa: E402
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

    def test_the_sample_answer_is_read_by_the_adapter_into_the_same_result(self):
        wire = codec.to_json(S.OTHERS["DelegateResult"])
        self.assertNotIn("v", wire)
        self.assertEqual(codec.from_json(delegate.DelegateResult, wire), S.OTHERS["DelegateResult"])
        r = delegate_wire.result_of(wire)
        st, facts = r.stop, S.OTHERS["DelegateResult"].stop
        self.assertEqual(st, facts)
        self.assertEqual((r.worker, r.exit_code, r.first_error), (S.OTHERS["DelegateResult"].worker, -15, "429 rate limited"))

    def test_a_done_answer_has_a_null_stop(self):
        wire = {**codec.to_json(S.OTHERS["DelegateResult"]), "stop": None}
        self.assertIsNone(delegate_wire.result_of(wire).stop)
        self.assertIsNone(codec.from_json(delegate.DelegateResult, wire).stop)

    def test_the_run_argv_is_built_by_the_request_alone(self):
        req = delegate.RunRequest(role="worker", brief_path="b", cwd="/w", schema_path="s", parent="p", task="t", title="T",
                                  timeout_s=60, idle_s=30)
        argv = req.to_argv("py", "r")
        self.assertEqual(argv[:3], ["py", "r", "run"])
        self.assertEqual(argv[argv.index("--timeout") + 1], "60")
        self.assertEqual(argv[argv.index("--idle") + 1], "30")
        self.assertEqual(delegate.RunRequest(role="worker", brief_path="b", cwd="/w", schema_path="s").to_argv("py", "r").count("--timeout"), 0)

    def test_engine_only_is_one_flag_per_recipe_and_none_by_default(self):
        base = dict(role="worker", brief_path="b", cwd="/w", schema_path="s")
        argv = delegate.RunRequest(**base, engine_only=["check", "unity-tests"]).to_argv("py", "r")
        self.assertEqual([argv[i + 1] for i, x in enumerate(argv) if x == "--engine-only"], ["check", "unity-tests"])
        self.assertNotIn("--engine-only", delegate.RunRequest(**base).to_argv("py", "r"))


if __name__ == "__main__":
    unittest.main()
