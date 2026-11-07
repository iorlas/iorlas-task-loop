"""LAND-stage engine test helpers and review fixtures."""
import copy
import types
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from support import gitq
from support.builders import make_engine
from support.engine_case import EngineTest, delegate_stack
from support.push_race import PushRace
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.run import engine
from tlkernel.checks import CheckRun
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tlslots import config as wslots_config
from tltestkit import fake_route
from tltestkit.checks import res
from tltestkit.plans import CLEAN, PLAN, WRITE, finding, review
from tlwork.write.newfiles import NewFiles


class EngineLandMixin:
    def run_push_race(self, rejections=1, failure="", plan=PLAN, resume_failed_fix=False, **cfg):
        """Advance a local remote immediately before each rejected push, under the real land lock (support/push_race.py)."""
        self.race_runs = getattr(self, "race_runs", 0) + 1
        cfg.setdefault("land_optimistic_tries", 0)  # these cells: the gate inside one lock (the outside gate: test_gate_outside_lock)
        race = PushRace(self, self.race_runs, rejections, failure)
        self.race_origin = race.origin
        return race.run(plan, resume_failed_fix, cfg, CLEAN, WRITE, review(findings=[finding("high")]))


class StrayWriteScript(fake_route.Script):
    """A writer whose play-mode run leaves Unity's scene and its .meta behind (lifesim-fld.6)."""

    def reply(self, role, prompt, schema, cwd, resume, *a, **kw):
        if role == "worker":
            d = Path(cwd, "client", "Assets")
            d.mkdir(parents=True, exist_ok=True)
            (d / "InitTestScene123.unity").write_text("scene\n")
            (d / "InitTestScene123.unity.meta").write_text("meta\n")
        return super().reply(role, prompt, schema, cwd, resume, *a, **kw)


class LandReviewBase(EngineLandMixin, EngineTest):
    STRAY: ClassVar[Any] = ["client/Assets/InitTestScene123.unity", "client/Assets/InitTestScene123.unity.meta"]

    def engine_at_land(self, attrs=None, **cfg):
        plan = {"stages": [{"goal": "g", "files": ["f.txt", "docs/"], "checks": [], "hard": False}]}
        return make_engine(self.wt, cfg=cfg, store=self.store, attrs=dict({"plan_data": plan}, **(attrs or {})))

    def staged(self):
        return sorted(gitq.git("diff", "--cached", "--name-only", cwd=str(self.wt)).split())

    def make_files(self, *names):
        for n in names:
            (self.wt / n).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / n).write_text("x\n")

    def run_with(self, script):
        with delegate_stack(script, "/r.py"):
            self.eng = engine.Engine(
                BeadId("t-1"),
                str(self.wt),
                wslots_config.load_cfg(str(self.wt), port_git()),
                store=self.store,
                env=snapshot(),
                spawner=real_spawner(),
                git=port_git(), who=who())
            return self.eng.run()

    def landed(self):
        return sorted(gitq.git("show", "--name-only", "--format=", "origin/main", cwd=str(self.wt)).split())

    CFG_CHECKS: ClassVar[Any] = [{"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"},
                  {"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"},
                  {"id": "unity-play-tests", "cmd": "just unity-play-tests", "group": "tests"}]

    def verifier(self, attrs=None, **cfg):
        return self.engine_at_land(dict({
            "unchecked": [], "verified": [], "steps": mock.Mock(), "comment": mock.Mock(),
            "briefs": types.SimpleNamespace(text=lambda: "the task"), "last_flag": "",
            "plan_data": copy.deepcopy(PLAN)}, **(attrs or {})), **cfg)

    YXBB6 = ("I did not re-run the whole Sim.Properties suite or the just unity-* checks. The engine ran the suite, and it "
             "passed. The unity checks were skipped because nothing changed under client/**... the claim that the engine ran "
             "the suite has no saved log, so I cannot prove it.")

    SUITE = "tests/Sim.Properties/bin/Debug/net10.0/Sim.Properties --filter-class '*SleepSkipTests'"

    def engine_checks(self, **over):
        rows = [
            res("just fmt-check", 0, id="fmt", group="static", secs=4, log="checks/00-fmt.r1.log"),
            res("just unity-analyzers", None, id="unity-analyzers", group="static", why="no change under client/**"),
            res("just unity-tests", None, id="unity-tests", why="no change under client/**, content/**"),
            res(self.SUITE, 0, id=self.SUITE, group="acceptance", secs=3, log="checks/06-tests_Sim.Properties.r2.log", tail="succeeded: 4"),
        ]
        return [r.replace(**over.get(r.id, {})) for r in rows]

    def evidenced(self, checks=None, attrs=None):
        e = self.verifier(attrs, checks=self.CFG_CHECKS[:2], gate="just check")
        e.last_run = CheckRun(round=1, tree=e.checkout.tree_hash(), results=checks or self.engine_checks())
        return e

    def reviewer_brief(self, cap=40000):
        script = fake_route.Script({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        with mock.patch.object(NewFiles, "STAGE_DIFF_CAP", cap):
            assert self.run_with(script) == 0
        return next(p for c, p in zip(script.calls, script.prompts, strict=False) if c[0] == "reviewer")
