"""tl-bxk.13: stage handoffs (docs/design/stages.md). Reuses test_engine's harness without re-running its tests."""
import json
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import (
    procsim,
    tools,
)
from support.builders import make_engine
from support.engine_case import CLEAN, HAS_F, PLAN, WRITE, lint

from taskloop.adapters import procs as sproc
from taskloop.adapters.check_probe import PathProbe
from taskloop.contracts.argv import argv_of


class StagesTest(te.EngineTest):
    def probe(self):
        return PathProbe(cast(Any, self).wt, sproc.current_env())

    wt: Path

    def created(self):
        return [a[1] for a in self.bd_calls if a and a[0] == "create"]


class Handoff(StagesTest):
    """13.6, 13.7: the rounds reach the planner of an amend; lows are not listed twice; a big writer starts the next stage fresh."""


    TWO: ClassVar[Any] = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")])

    def boundary(self, ctx_k, **cfg):
        path = Path(self.tmp.name, "session.jsonl")
        n = int(ctx_k * 1000) - 100
        path.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 3, "cache_read_input_tokens": n, "cache_creation_input_tokens": 97}}}) + "\n")
        extra = {"family": "claude", "transcript": str(path)}
        return self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                               j_extra={"write": [extra, extra]}, **cfg)


class SharedNotes(StagesTest):
    """13.8: the tasks of a repo share what is running, what landed and which tests are flaky."""

    def eng_(self, **attrs):
        return make_engine(self.wt, store=self.store, attrs=attrs)


class Fdyo(StagesTest):
    """13.11-13.14, from the lifesim-fdyo run (15.7M tokens): checks only the engine can pass, a late fresh writer, a check that
    cannot run, slow tests before a fast verdict."""

    PASS = "true"


class Executable(StagesTest):
    """tl-bxk.13.16.2: a plan check must be able to start; an accepted stage's promised files must exist on resume."""


    def problems(self, cmd, probe=None, **kw):
        return lint.command_problems(argv_of(cmd), probe or self.probe(), **kw)
    def test_a_just_recipe_must_exist_in_the_tree(self):
        tools.need(self, "just")
        self.enterContext(tools.on_path("just"))
        (self.wt / "justfile").write_text("fmt-check:\n\techo ok\n")
        self.assertEqual(self.problems("just fmt-check"), [])
        bad = self.problems("just unity-play-tests")
        self.assertEqual(len(bad), 1)
        self.assertIn("no recipe unity-play-tests", bad[0])
        self.assertIn("fmt-check", bad[0])
    def test_just_aliases_private_recipes_options_and_a_recipe_a_stage_adds(self):
        tools.need(self, "just")
        self.enterContext(tools.on_path("just"))
        (self.wt / "justfile").write_text("alias ci := check\ncheck:\n\techo ok\n_private:\n\techo p\n")
        for ok in ("just ci", "just _private", "just --justfile justfile check", "just --set v x check", "just -d . check", "just check"):
            self.assertEqual(self.problems(ok), [], ok)
        self.assertEqual(len(self.problems("just nope")), 1)
        self.assertEqual(self.problems("just newrecipe", made=["justfile"]), [])  # a stage adds it
        (self.wt / "justfile").write_text("newrecipe:\n\techo n\n")  # a rebase changes the file: seen at once
        self.assertEqual(self.problems("just newrecipe"), [])


    PATH1 = ".task/t-1/evidence/sleeper-on-bed.txt"

    def writes_path1(self, cwd, env):
        (cwd / self.PATH1).parent.mkdir(parents=True, exist_ok=True)
        (cwd / self.PATH1).write_text("ok")
        return 0, ""

    def two_stage(self):
        return dict(
            PLAN,
            stages=[
                dict(
                    PLAN["stages"][0],
                    goal="stage one",
                    checks=[procsim.fake(f"writes {self.PATH1}", self.writes_path1), HAS_F],
                ),
                dict(PLAN["stages"][0], goal="stage two", checks=[f"test -s {self.PATH1}"]),
            ],
        )


class Ledger(StagesTest):
    eng: Any
    """tl-bxk.13.16.1: the plan says how each criterion is proved; review and verify go by it, not by the wording of an item."""

    LEFT: ClassVar[Any] = [{"title": "Import the chosen prefabs and add object rows", "why": "next bead"}]
    FILE: ClassVar[Any] = {"criterion": "Record the plan's follow-up issues about stale layer prose and bead wording", "check": "",
            "proved_by": "engine_step", "via": "file_beads"}
    DEFER: ClassVar[Any] = {"criterion": "A follow-up bead imports the chosen prefabs and adds object rows", "check": "",
             "proved_by": "leftover", "via": "Import the chosen prefabs and add object rows"}

    def plan(self, **kw):
        return dict(PLAN, cases=[self.FILE, self.DEFER, {"criterion": "f exists", "check": HAS_F, "proved_by": "check"}],
                    leftovers=self.LEFT, **kw)


if __name__ == "__main__":
    unittest.main()
