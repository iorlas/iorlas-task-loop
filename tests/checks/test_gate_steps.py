"""Engine tests: the gate as a registry of checks. A check says `run`: stage (the round after each write), gate (a step of land's gate) or
both; the gate runs its steps through the checks' own machinery and cache."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.check_host import CheckHostCase
from support.plans import CLEAN, PLAN, WRITE

# isort: split
from support.logs import records

from taskloop.contracts.checks import Check
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.specs import due, engine_digest, gate_items, items_of

STEP = "true"
RED_ON_D2 = procsim.default("red-on-d2", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, f"step saw {procsim.f_txt(cwd)}"))
ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}


def ends(eng, name):
    """{check name: its CheckEnd record} of the check log (the starts name them)."""
    names = {r["id"]: r["check"] for r in records(eng, "check_start")}
    return {names[r["id"]]: r for r in records(eng, "check_end")}


class GateSteps(CheckHostCase):
    def test_check_run_carries_the_identity_from_before_execution(self):
        def change_files(cwd, env):
            (Path(cwd) / "f.txt").write_text("changed by gate")
            return 0, ""

        cmd = procsim.fake("change-files", change_files)
        eng = self.checks_engine(checks=[{"id": "mutator", "cmd": cmd, "run": "gate"}])
        tree = eng.checkout.tree_hash()
        base = eng.git.rev_parse(str(eng.wt), eng.cfg.base)
        config = engine_digest(eng.cfg)
        run = eng.checker.run_items(gate_items(eng.cfg))
        assert (run.tree, run.base, run.config) == (tree, base, config)
        assert eng.checkout.tree_hash() != tree

    def test_a_check_with_run_stage_is_not_in_the_gate(self):
        eng = self.checks_engine(checks=[{"id": "s", "cmd": STEP}, {"id": "g", "cmd": STEP, "run": "gate"},
                                         {"id": "b", "cmd": STEP, "run": "both"}])
        assert [c.id for c in gate_items(eng.cfg)] == ["g", "b"]
        assert [c.id for c in items_of(eng.cfg, [])] == ["s", "b"]  # and a gate-only step is no stage check






class When(CheckHostCase):
    def test_when_uses_the_inputs_glob_dialect_star_stays_in_one_folder(self):
        c = Check(id=CheckId("w"), cmd="true", when=["client/*.cs", "src/**", "{a,b}/x"])
        assert due(c, ["client/A.cs"])
        assert not due(c, ["client/deep/A.cs"])  # fnmatch's * crossed folders: the same glob said two things
        assert due(c, ["src/a/b/c.py"])
        assert due(c, ["b/x"])
        assert not due(c, ["docs/x"])
        assert due(Check(id=CheckId("n"), cmd="true"), [])
