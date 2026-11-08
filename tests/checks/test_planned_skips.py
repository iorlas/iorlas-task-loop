"""Only `when` skips of a completed clean round satisfy the gate for its exact diff."""
from support.check_host import CheckHostCase

from tlgate.cache import is_green
from tlgate.domain.specs import gate_items
from tlkernel import wire
from tlkernel.checks import CheckResult
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha
from tltestkit.plans import FALSE


class PlannedSkips(CheckHostCase):
    def memo(self):
        host = self.eng.checker.host
        return self.eng.checker._memo(host.checkout.tree_hash(), host.git.rev_parse(str(host.wt), host.cfg.base))

    def green(self, step):
        memo = self.memo()
        return is_green(memo.stores, memo.repo, CheckId(step), memo.keys.tree, memo.base)

    def test_a_clean_planned_skip_is_recorded_with_reason_and_green_only_for_this_diff(self):
        self.eng = self.checks_engine(checks=[{"id": "coverage", "cmd": "true", "run": "gate", "when": ["ui/**"]}])
        assert not self.green("coverage")  # never run is still red
        items = gate_items(self.eng.cfg)
        run = self.eng.checker.run_items(items)
        assert [(r.status, r.planned, r.why) for r in run] == [("skipped", True, "no change under ui/**")]
        memo = self.memo()
        assert self.green("coverage")
        assert memo.hit(memo.planned_key(items[0])) is None  # a planned skip cannot supply a cached pass
        for tree, base in ((TreeSha("other"), memo.base), (memo.keys.tree, BaseSha("other"))):
            assert not is_green(memo.stores, memo.repo, CheckId("coverage"), tree, base)
        assert not self.green("never-ran")
        all_run = self.eng.checker.run_items(items, everything=True)
        assert [(r.status, r.planned, r.cached) for r in all_run] == [("passed", False, False)]

    def test_a_planned_skip_before_a_red_is_not_recorded(self):
        self.eng = self.checks_engine(checks=[
            {"id": "coverage", "cmd": "true", "group": "static", "run": "gate", "when": ["ui/**"]},
            {"id": "red", "cmd": FALSE, "group": "tests", "run": "gate"},
        ])
        run = self.eng.checker.run_items(gate_items(self.eng.cfg))
        assert [(r.status, r.planned) for r in run] == [("skipped", True), ("failed", False)]
        assert not self.green("coverage")

    def test_a_failed_first_skip_is_not_planned_or_recorded(self):
        self.eng = self.checks_engine(checks=[
            {"id": "red", "cmd": FALSE, "group": "static", "run": "gate"},
            {"id": "coverage", "cmd": "true", "group": "tests", "run": "gate", "when": ["ui/**"]},
        ])
        run = self.eng.checker.run_items(gate_items(self.eng.cfg))
        assert (run[1].status, run[1].planned, run[1].why) == ("skipped", False, "static failed first")
        assert not self.green("coverage")

    def test_a_planned_skip_in_another_track_is_not_recorded_when_a_track_fails(self):
        self.eng = self.checks_engine(checks=[
            {"id": "coverage", "cmd": "true", "run": "gate", "when": ["ui/**"], "track": "a"},
            {"id": "red", "cmd": FALSE, "run": "gate", "track": "b"},
        ])
        self.eng.checker.run_items(gate_items(self.eng.cfg))
        assert not self.green("coverage")

    def test_a_clean_multitrack_round_records_planned_skips_after_folding(self):
        self.eng = self.checks_engine(checks=[
            {"id": "coverage", "cmd": "true", "run": "gate", "when": ["ui/**"], "track": "a"},
            {"id": "lint", "cmd": "true", "run": "gate", "track": "b"},
        ])
        self.eng.checker.run_items(gate_items(self.eng.cfg))
        assert self.green("coverage")
        assert self.green("lint")

    def test_a_gone_producer_skip_is_not_planned_or_green_in_a_clean_round(self):
        self.eng = self.checks_engine(checks=[
            {"id": "producer", "cmd": "true", "run": "gate", "when": ["ui/**"]},
            {"id": "consumer", "cmd": "true", "run": "gate", "reads": ["producer"], "when": ["ui/**"]},
        ])
        run = self.eng.checker.run_items(gate_items(self.eng.cfg))
        assert [(r.status, r.planned) for r in run] == [("skipped", True), ("skipped", False)]
        assert self.green("producer")
        assert not self.green("consumer")

    def test_old_wire_results_default_to_unplanned_and_planned_skips_round_trip(self):
        res = CheckResult(id=CheckId("c"), cmd="c", group="tests", exit=None, status="skipped", planned=True)
        assert wire.load(CheckResult, wire.dump(res)) == res
        old = wire.dump(res)
        del old["planned"]
        assert not wire.load(CheckResult, old).planned
