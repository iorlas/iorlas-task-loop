"""Live reload (tl-7y6.9): no step runs on stale code. The engine moves to a newer install at a step boundary by exec
(simulated here with an injected exec function), the bead finishes on the new version with the same run id, a broken
install is refused and recorded, delegate is resolved per call, and nothing reloads a module in place."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
sys.path.insert(0, str(ROOT / "tests"))
import engine  # noqa: E402
from support.builders import cfg_with  # noqa: E402
import seams  # noqa: E402
from taskloop_dash.views import graph  # noqa: E402
import loop  # noqa: E402
from taskloop_dash.views import roadmap  # noqa: E402
import test_engine as te  # noqa: E402
import tl  # noqa: E402
from support.fakes import as_bead  # noqa: E402
import delegate_link as dl  # noqa: E402
from support import fake_route  # noqa: E402

BREAK_PLAN = ("    def plan(self, again=False):\n", "    def plan(self, again=False):\n        raise RuntimeError('planted: cannot plan')\n")


class Reload(unittest.TestCase):
    # the engine fixture of test_engine (a repo with an origin, bd and the landing faked), without its tests
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd

    def setUp(self):  # noqa: F811
        te.EngineTest.setUp(self)
        self.cache = Path(self.tmp.name, "cache")
        here = self.install("0.1.0", fake=True)
        for p in (mock.patch.object(tl, "HERE", here), mock.patch.object(engine, "plugin_version", return_value="0.1.0")):
            p.start()
            self.addCleanup(p.stop)
        self.execs = []
        for p in (mock.patch.object(dl, "resolve", return_value=self.res("/fake/route.py")),):  # no delegate in an isolated HOME
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def res(route):
        return dl.Resolved(Path(route).parent, route, fake_route.CONTRACT, "explicit")

    def install(self, ver, plant=None, fake=False):
        """An installed version: a copy of this checkout's skill (its selftest is the real one), or a stub for the running one."""
        d = self.cache / ver / "skills" / "task-loop"
        if fake:
            d.mkdir(parents=True)
        else:
            shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__", "dash"))
            shutil.copytree(ROOT / "src", d.parents[1] / "src", ignore=shutil.ignore_patterns("__pycache__"))
        (d.parents[1] / ".claude-plugin").mkdir(exist_ok=True)
        (d.parents[1] / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": ver}))
        if plant:
            f = d / "engine.py"
            text = f.read_text(encoding="utf-8")
            self.assertIn(plant[0], text)
            f.write_text(text.replace(plant[0], plant[1], 1), encoding="utf-8")
        return d

    def events(self):
        f = tl.config_dir() / "events.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def engine_for(self, script, **cfg):
        c = engine.load_cfg(str(self.wt))
        c = cfg_with(c, **{"reflect": False, **cfg})
        eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
        eng.argv = ["run-task", "t-1", "--worktree", str(self.wt), "--fresh", "--outcome-file", "/x/out.json"]

        def fake_exec(argv):
            self.execs.append({"argv": argv, "env": json.loads(os.environ["TL_REEXEC"]), "marker": engine.read_reexec("t-1")})
        eng.exec_fn = fake_exec
        return eng

    def patches(self, script, during=None):
        """The delegate faked; `during` runs on the first writer call (a release lands mid-bead)."""
        fired = []

        class Runner:  # the script as the process seam, with `during` run on the first writer call
            def __call__(this, cmd, **kw):
                if during and not fired and cmd[3] == "worker":
                    fired.append(1)
                    during()
                return script(cmd, **kw)

            def __getattr__(this, name):
                return getattr(script, name)
        return (mock.patch.object(seams.DelegateRoute, "runner", lambda self, *a, **k: Runner()), mock.patch.object(engine.time, "sleep"))

    def run_with(self, eng, script, during=None):
        ps = self.patches(script, during)
        for p in ps:
            p.start()
        try:
            return eng.run()
        finally:
            for p in ps:
                p.stop()

    # -- point 5: a newer install mid-bead -> exec at the next boundary, same run id, finished on the new version
    def test_a_newer_install_mid_bead_execs_at_the_next_step_boundary_and_the_bead_finishes_on_it_with_the_same_run(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        eng = self.engine_for(script)
        self.run_with(eng, script, during=lambda: self.install("0.2.0"))
        self.assertTrue(eng.moved)
        run = eng.log_path.stem
        self.assertEqual(len(self.execs), 1)
        ex = self.execs[0]
        self.assertEqual(ex["argv"][:2], [sys.executable, str(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py")])
        self.assertEqual(ex["argv"][2:], ["run-task", "t-1", "--outcome-file", "/x/out.json", "--worktree", str(self.wt)])  # no --fresh
        self.assertEqual(ex["env"]["run"], run)
        self.assertEqual((ex["marker"]["from"], ex["marker"]["to"], ex["marker"]["step"]), ("0.1.0", "0.2.0", "land"))
        # the stage was accepted on 0.1.0; the checkpoint says land; the move is one event old -> new
        ck = json.loads(eng.checkpoint_path().read_text())
        self.assertEqual((ck["step"], ck["run"]), ("land", run))
        ev = [e for e in self.events() if e["kind"] == "reload"]
        self.assertEqual([(e["old"], e["new"], e["who"], e["run"]) for e in ev], [("0.1.0", "0.2.0", "engine", run)])
        self.assertEqual([c[0] for c in script.calls], ["planner", "worker", "reviewer"])  # land and close have not run yet
        self.assertEqual(self.closed, [])
        # the new image: same environment, the TL_REEXEC hand-over, the same checkpoint and log
        with mock.patch.dict(os.environ, {"TL_REEXEC": json.dumps(ex["env"])}), mock.patch.object(engine, "plugin_version", return_value="0.2.0"):
            eng2 = self.engine_for(script)
            self.assertEqual(eng2.log_path, eng.log_path)  # same run id, same log and run dir
            self.assertEqual(eng2.run_dir, eng.run_dir)
            self.assertNotIn("TL_REEXEC", os.environ)  # taken: no child inherits it
            rc = self.run_with(eng2, script)
        self.assertEqual(rc, 0)
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertFalse(engine.reexec_path("t-1").exists())  # a run that ended is no crash after an exec
        logs = [json.loads(x) for x in eng.log_path.read_text().splitlines()]
        self.assertEqual(len([x for x in logs if x["kind"] == "run_start"]), 1)  # one run record for the one run
        self.assertTrue([x["text"] for x in logs if x["kind"] == "note" and x["text"].startswith("task-loop 0.")][-1].startswith("task-loop 0.2.0 took"))
        self.assertTrue(any("took over run %s from 0.1.0" % run in x.get("text", "") for x in logs))
        self.assertEqual([x["step"] for x in logs if x["kind"] == "reload"], ["land"])  # the move is a record of its own
        self.assertEqual(eng2.stats["writes"], eng.stats["writes"])  # the counters went across

    def test_the_move_slot_is_handed_on_and_given_back_by_the_new_image(self):
        self.assertEqual(engine.reexec_args(["run-task", "t-1", "--slot", "any", "--wait", "--worktree", "/w", "--quiet"], "s2", "/wt"),
                         ["run-task", "t-1", "--quiet", "--slot", "s2", "--worktree", "/wt"])
        self.assertIsNone(engine.reexec_args(["loop", "--repo", "."], "", "/wt"))
        with mock.patch.dict(os.environ, {"TL_REEXEC": json.dumps({"run": "x", "owned": "s2"})}):
            self.assertTrue(engine._handed_slot("s2"))
            self.assertFalse(engine._handed_slot("s3"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TL_REEXEC", None)
            self.assertFalse(engine._handed_slot("s2"))

    def test_a_dry_run_and_a_run_not_started_by_run_task_never_move(self):
        self.install("0.2.0")
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        eng = self.engine_for(script)
        eng.argv = ["something-else"]
        self.assertEqual(self.run_with(eng, script), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([e for e in self.events() if e["kind"] == "reload"], [])

    # -- a broken install keeps the old one running, one red event, tested once
    def test_a_broken_install_keeps_the_old_one_running_with_one_red_event_and_is_tested_once(self):
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        eng = self.engine_for(script)
        tests = []
        real = loop.selftest_of
        with mock.patch.object(loop, "selftest_of", side_effect=lambda here: tests.append(here) or real(here)):
            rc = self.run_with(eng, script, during=lambda: self.install("0.2.0", plant=BREAK_PLAN))
        self.assertEqual(rc, 0)  # finished on 0.1.0
        self.assertEqual(self.execs, [])
        red = [e for e in self.events() if e["kind"] == "reload_refused"]
        self.assertEqual(len(red), 1)
        self.assertEqual((red[0]["version"], red[0]["running"], red[0]["who"]), ("0.2.0", "0.1.0", "engine"))
        self.assertIn("planted: cannot plan", red[0]["why"])
        self.assertEqual(len(tests), 1)  # the next boundaries read bad-versions.json instead of testing it again
        self.assertEqual(list(json.loads((tl.config_dir() / "bad-versions.json").read_text())), ["0.2.0"])
        self.assertEqual([e for e in self.events() if e["kind"] == "reload"], [])

    def test_a_refused_version_is_tried_again_when_it_is_installed_again_and_a_newer_one_is_tried(self):
        self.install("0.2.0", plant=BREAK_PLAN)
        self.assertEqual(loop.vet_newer()[:2], ("0.2.0", self.cache / "0.2.0"))
        self.assertIsNone(loop.vet_newer())  # refused, key unchanged: not looked at
        shutil.rmtree(self.cache / "0.2.0")
        self.install("0.2.0")  # the same number, re-released
        self.assertIsNone(loop.vet_newer()[2])
        self.install("0.3.0")
        self.assertEqual(loop.vet_newer()[0], "0.3.0")

    # -- the crash after an exec: the loop puts the run back on the version it came from, once
    def test_a_run_task_that_dies_right_after_the_exec_is_restarted_once_on_the_old_version(self):
        old = self.cache / "0.1.0" / "skills" / "task-loop"
        spawned = []

        class Child:
            def __init__(self, cmd):
                self.pid, self.cmd = 4242, cmd

            def wait(self, timeout=None):
                if len(spawned) == 2:  # the fallback run gives its outcome
                    Path(self.cmd[self.cmd.index("--outcome-file") + 1]).write_text(json.dumps({"outcome": "landed"}))
                    return 0
                engine.reexec_path("t-1").parent.mkdir(parents=True, exist_ok=True)
                engine.reexec_path("t-1").write_text(json.dumps({"run": "t-1-20261026-120000", "bead": "t-1", "from": "0.1.0", "to": "0.2.0",
                                                                  "from_dir": str(old), "t": time.time()}))
                return 1  # import error of the new image: no outcome, the note is still there

        spawned_env = []

        def spawn(cmd, log):
            spawned.append(cmd)
            if len(spawned) == 2:
                spawned_env.append(json.loads(os.environ["TL_REEXEC"]))
            return Child(cmd)
        (old / "tl.py").write_text("")
        self.install("0.2.0")
        repo = str(self.wt)
        with mock.patch.object(loop, "spawn", side_effect=spawn), mock.patch.object(loop, "write_state"), \
                mock.patch.object(loop, "say") as say, mock.patch.dict(os.environ, {}):
            # the first child is the one that exec'd: its note appears while it runs
            r = loop.run_bead(repo, as_bead({"id": "t-1"}), "s1", str(self.wt), "sb-1", 0.0)
            leaked = os.environ.get("TL_REEXEC")
        self.assertEqual(r["outcome"], "landed")
        self.assertEqual(len(spawned), 2)
        self.assertEqual(spawned[1][1], str(old / "tl.py"))
        self.assertIsNone(leaked)  # the loop's own environment keeps no hand-over for its later run-tasks
        self.assertEqual(spawned_env[0]["run"], "t-1-20261026-120000")  # the fallback child got it
        fb = [e for e in self.events() if e["kind"] == "reload_fallback"]
        self.assertEqual([(e["old"], e["new"]) for e in fb], [("0.2.0", "0.1.0")])
        self.assertIn("0.2.0", json.loads((tl.config_dir() / "bad-versions.json").read_text()))
        self.assertTrue(any("RED" in str(c) for c in say.call_args_list))
        self.assertFalse(engine.reexec_path("t-1").exists())

    # -- point 2: delegate is resolved per call, never held
    def test_delegate_route_is_resolved_again_each_call(self):
        c = engine.load_cfg(str(self.wt))
        with mock.patch.object(dl, "resolve", side_effect=[self.res("/a/route.py"), self.res("/b/route.py"), self.res("/b/route.py")]) as fr:
            eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
            self.assertEqual(eng.delegate_route(), "/b/route.py")
            self.assertEqual(eng.delegate_route(), "/b/route.py")
            self.assertEqual(fr.call_count, 3)

    def test_the_engine_and_lanes_never_store_a_resolved_route_or_a_delegate_module_across_calls(self):
        bad = []
        for f in [SRC / "engine.py", *sorted((SRC / "lanes").glob("*.py"))]:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            parents = {}
            for n in ast.walk(tree):
                for ch in ast.iter_child_nodes(n):
                    parents[ch] = n

            def inside(n):
                while n in parents:
                    n = parents[n]
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        return n.name
                return None
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "resolve" \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "dl":
                    where = inside(n)
                    if where not in ("__init__", "delegate_route", None) and f.name == "engine.py":
                        bad.append("%s: dl.resolve called in %s" % (f.name, where))
                    stmt = parents.get(n)
                    while stmt is not None and not isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.Module)):
                        stmt = parents.get(stmt)
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if isinstance(t, ast.Attribute) and not (f.name == "engine.py" and t.attr == "route" and where in ("__init__", "delegate_route")):
                                bad.append("%s:%d stores dl.resolve() in .%s" % (f.name, n.lineno, t.attr))
                            if isinstance(t, ast.Name) and where is None:
                                bad.append("%s:%d keeps dl.resolve() in module global %s" % (f.name, n.lineno, t.id))
                if isinstance(n, ast.Assign) and f.name == "engine.py":  # no delegate module object held: self.x = <module>
                    v = n.value
                    if isinstance(v, ast.Call) and getattr(v.func, "attr", "") in ("import_module", "spec_from_file_location", "module_from_spec"):
                        bad.append("%s:%d holds an imported delegate module" % (f.name, n.lineno))
        self.assertEqual(bad, [])

    # -- point 3: re-exec is the only reload path
    def test_nothing_in_the_skill_reloads_a_module(self):
        hits = []
        for f in SRC.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            for k, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if re.search(r"importlib\.reload|\breload\(", line):
                    hits.append("%s:%d" % (f.relative_to(SRC), k))
        self.assertEqual(hits, [])

    # -- point 4: loop state and dashboard lane
    def test_loop_state_names_the_running_version_and_code_dir(self):
        repo = str(self.wt)
        loop.write_state(repo, pid=os.getpid(), started=1.0)
        st = loop.read_state(repo)
        self.assertEqual((st["version"], st["code_dir"]), ("0.1.0", str(tl.HERE)))

    def test_releases_behind_counts_installed_versions_above_it(self):
        for v in ("0.2.0", "0.10.0"):
            self.install(v, fake=True)
            (self.cache / v / "skills" / "task-loop" / "tl.py").write_text("")
        (self.cache / "0.1.0" / "skills" / "task-loop" / "tl.py").write_text("")
        with mock.patch.object(tl, "cache_dirs", return_value={v: self.cache / v for v in ("0.1.0", "0.2.0", "0.10.0")}):
            self.assertEqual(tl.releases_behind("0.1.0"), 2)
            self.assertEqual(tl.releases_behind("0.2.0"), 1)
            self.assertEqual(tl.releases_behind("0.10.0"), 0)

    def test_the_dashboard_lane_shows_the_engine_version_and_how_many_releases_it_lags(self):
        self.assertEqual(roadmap.lag("0.23.40", ["0.23.40", "0.23.41", "0.23.42", "0.9.0"]), 2)
        self.assertEqual(roadmap.lag("0.23.42", ["0.23.40", "0.23.42"]), 0)
        self.assertEqual(roadmap.lag("", ["0.23.42"]), 0)
        lanes, _ = roadmap.lanes_of(["s1"], {"t-1": "s1"}, [{"pid": 1, "slot": "s1", "bead": "t-1", "since": 1, "started": 1, "version": "0.23.42"}])
        lanes[0]["engine"] = "0.23.40"
        b = {"id": "t-1", "title": "t", "status": "in_progress", "labels": ["auto"], "issue_type": "task", "priority": 2, "dependencies": [], "parent": None}
        g = graph.build([b], {"pick_label": "auto", "skip_labels": []}, set(), {"t-1"}, (), now=time.time())
        out = roadmap.build(g, lanes, [], [], [], {}, now=time.time(), installed=["0.23.40", "0.23.41", "0.23.42"])
        self.assertEqual((out["lanes"][0]["engine"], out["lanes"][0]["lags"]), ("0.23.40", 2))
        html = (ROOT / "src" / "taskloop_dash" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("'engine '+esc(l.engine)", html)
        self.assertIn("'lags '+l.lags", html)


if __name__ == "__main__":
    unittest.main()
