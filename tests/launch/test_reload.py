"""Live reload (tl-7y6.9): no step runs on stale code. The engine moves to a newer install at a step boundary by exec
(simulated here with an injected exec function), the bead finishes on the new version with the same run id, a broken
install is refused and recorded, delegate is resolved per call, and nothing reloads a module in place."""

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support.checkpoints import read_ck  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from support import engine_case as te  # noqa: E402
from support import (  # noqa: E402
    fake_route,
    looptest,
)
from support.builders import cfg_with  # noqa: E402
from support.fake_beads import FakeBeads  # noqa: E402
from support.fakes import as_bead  # noqa: E402
from support.narrow import must  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.adapters import (  # noqa: E402
    gitrepo,
    ident,
    procs,
)
from taskloop.app.launch import loop as wloop  # noqa: E402
from taskloop.app.loop.run import BeadRun, Where  # noqa: E402
from taskloop.app.release import (  # noqa: E402
    catalog,
    reexec,
    seams,
)
from taskloop.app.run import (  # noqa: E402
    engine,
    entry,
)
from taskloop.app.wire import slots as wslots  # noqa: E402

PLAN_DEF = "    def plan(self, again: bool = False) -> dict[str, Any]:\n"
BREAK_PLAN = (PLAN_DEF, PLAN_DEF + "        raise RuntimeError('planted: cannot plan')\n", "src/taskloop/app/plan/planner.py")


class Reload(te.EngineTest):
    # the engine fixture of test_engine (a repo with an origin, bd and the landing faked), without its tests

    def setUp(self):
        te.EngineTest.setUp(self)
        self.cache = Path(self.tmp.name, "cache")
        here = self.install("0.1.0", fake=True)
        self.here = here  # the install the engine under test runs from (wloop.newer / build take it)
        p = mock.patch.object(ident, "plugin_version", return_value="0.1.0")
        p.start()
        self.addCleanup(p.stop)
        self.execs = []
        for p in (mock.patch.object(dl, "resolve", return_value=self.res("/fake/route.py")),  # no delegate in an isolated HOME
                  mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(Path(self.tmp.name, "claude"))})):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def res(route):
        return dl.Resolved(Path(route).parent, route, fake_route.CONTRACT, "explicit")

    def install(self, ver, plant=None, fake=False):
        """An installed version: this checkout's skill and src (linked, not copied: only a planted break gets its own copy;
        nothing tests it before a move), or a stub for the running one."""
        d = self.cache / ver / "skills" / "task-loop"
        if fake:
            d.mkdir(parents=True)
        elif plant:
            shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("dash"))  # with __pycache__: the child imports warm, only the
            shutil.copytree(ROOT / "src", d.parents[1] / "src")  # planted file (newer mtime) compiles again
        else:
            d.parent.mkdir(parents=True)
            d.symlink_to(SRC, target_is_directory=True)
            (d.parents[1] / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (d.parents[1] / ".claude-plugin").mkdir(exist_ok=True)
        (d.parents[1] / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": ver}))
        if plant:
            f = d.parents[1] / plant[2]
            text = f.read_text(encoding="utf-8")
            self.assertIn(plant[0], text)
            f.write_text(text.replace(plant[0], plant[1], 1), encoding="utf-8")
        return d

    def events(self):
        f = ident.config_dir() / "events.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def engine_for(self, script, **cfg):
        c = wslots.load_cfg(str(self.wt))
        c = cfg_with(c, **{"reflect": False, **cfg})
        eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
        eng.argv = ["run-task", "t-1", "--worktree", str(self.wt), "--fresh", "--outcome-file", "/x/out.json"]

        def fake_exec(argv):
            self.execs.append({"argv": argv, "env": json.loads(os.environ["TL_REEXEC"]), "marker": reexec.read_reexec("t-1")})
        eng.exec_fn = fake_exec
        eng.newer_fn = lambda: wloop.newer(self.here)  # pyrefly: ignore[bad-assignment]
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
        return (mock.patch.object(seams.DelegateRoute, "runner", lambda self, *a, **k: Runner()), te.no_sleep_here())

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
        self.assertEqual(ex["argv"][:5], procs.script_argv(self.cache / "0.2.0" / "skills" / "task-loop" / "tl.py"))
        self.assertEqual(ex["argv"][5:], ["run-task", "t-1", "--outcome-file", "/x/out.json", "--worktree", str(self.wt)])  # no --fresh
        self.assertEqual(ex["env"]["run"], run)
        self.assertEqual((ex["marker"]["from"], ex["marker"]["to"], ex["marker"]["step"]), ("0.1.0", "0.2.0", "land"))
        # the stage was accepted on 0.1.0; the checkpoint says land; the move is one event old -> new
        ck = read_ck(eng)
        self.assertEqual((ck.step, ck.run), ("land", run))
        ev = [e for e in self.events() if e["kind"] == "reload"]
        self.assertEqual([(e["old"], e["new"], e["who"], e["run"]) for e in ev], [("0.1.0", "0.2.0", "engine", run)])
        self.assertEqual([c[0] for c in script.calls], ["planner", "worker", "reviewer"])  # land and close have not run yet
        self.assertEqual(self.closed, [])
        # the new image: same environment, the TL_REEXEC hand-over, the same checkpoint and log
        with (
            mock.patch.dict(os.environ, {"TL_REEXEC": json.dumps(ex["env"])}),
            mock.patch.object(ident, "plugin_version", return_value="0.2.0"),
        ):
            eng2 = self.engine_for(script)
            self.assertEqual(eng2.log_path, eng.log_path)  # same run id, same log and run dir
            self.assertEqual(eng2.run_dir, eng.run_dir)
            self.assertNotIn("TL_REEXEC", os.environ)  # taken: no child inherits it
            rc = self.run_with(eng2, script)
        self.assertEqual(rc, 0)
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(gitrepo.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")  # pyrefly: ignore[missing-attribute]
        self.assertFalse(reexec.reexec_path("t-1").exists())  # a run that ended is no crash after an exec
        logs = [json.loads(x) for x in eng.log_path.read_text().splitlines()]
        self.assertEqual(len([x for x in logs if x["kind"] == "run_start"]), 1)  # one run record for the one run
        self.assertTrue(
            [x["text"] for x in logs if x["kind"] == "note" and x["text"].startswith("task-loop 0.")][-1].startswith("task-loop 0.2.0 took")
        )
        self.assertTrue(any(f"took over run {run} from 0.1.0" in x.get("text", "") for x in logs))
        self.assertEqual([x["step"] for x in logs if x["kind"] == "reload"], ["land"])  # the move is a record of its own
        self.assertEqual(eng2.stats["writes"], eng.stats["writes"])  # the counters went across

    def test_the_move_slot_is_handed_on_and_given_back_by_the_new_image(self):
        self.assertEqual(reexec.reexec_args(["run-task", "t-1", "--slot", "any", "--wait", "--worktree", "/w", "--quiet"], "s2", "/wt"),
                         ["run-task", "t-1", "--quiet", "--slot", "s2", "--worktree", "/wt"])
        self.assertIsNone(reexec.reexec_args(["loop", "--repo", "."], "", "/wt"))
        with mock.patch.dict(os.environ, {"TL_REEXEC": json.dumps({"run": "x", "owned": "s2"})}):
            self.assertTrue(entry._handed_slot("s2"))
            self.assertFalse(entry._handed_slot("s3"))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TL_REEXEC", None)
            self.assertFalse(entry._handed_slot("s2"))

    def test_a_dry_run_and_a_run_not_started_by_run_task_never_move(self):
        self.install("0.2.0")
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        eng = self.engine_for(script)
        eng.argv = ["something-else"]
        self.assertEqual(self.run_with(eng, script), 0)
        self.assertEqual(self.execs, [])
        self.assertEqual([e for e in self.events() if e["kind"] == "reload"], [])

    def test_a_refused_version_is_skipped_until_it_is_installed_again_and_a_newer_one_is_taken(self):
        inst = wloop.installs(wloop.cfgdir(), here=self.here)
        self.install("0.2.0", plant=BREAK_PLAN)  # a copy: a link would share the files the install key is made of
        self.assertEqual(must(wloop.newer(self.here)), ("0.2.0", self.cache / "0.2.0"))
        inst.record_bad("0.2.0", "run-task died (exit 1) 3 s after the exec into it")  # what the crash fallback writes
        self.assertIsNone(wloop.newer(self.here))  # refused, key unchanged
        shutil.rmtree(self.cache / "0.2.0")
        self.install("0.2.0")  # the same number, re-released
        self.assertEqual(must(wloop.newer(self.here))[0], "0.2.0")
        self.install("0.3.0")
        self.assertEqual(must(wloop.newer(self.here))[0], "0.3.0")

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
                reexec.reexec_path("t-1").parent.mkdir(parents=True, exist_ok=True)
                reexec.reexec_path("t-1").write_text(
                    json.dumps(
                        {
                            "run": "t-1-20261026-120000",
                            "bead": "t-1",
                            "from": "0.1.0",
                            "to": "0.2.0",
                            "from_dir": str(old),
                            "t": time.time(),
                        }
                    )
                )
                return 1  # import error of the new image: no outcome, the note is still there

        spawned_env, pids = [], []

        def spawn(cmd, log, extra):
            spawned.append(cmd)
            pids.append(extra.get("TASK_LOOP_LOOP_PID"))
            if len(spawned) == 2:
                spawned_env.append(json.loads(extra["TL_REEXEC"]))
            return Child(cmd), mock.Mock()
        (old / "tl.py").write_text("")
        self.install("0.2.0")
        repo = str(self.wt)
        said = []
        with mock.patch.object(wloop, "spawn", side_effect=spawn), mock.patch.dict(os.environ, {}):
            env = wloop.build(repo, store=FakeBeads(), here=self.here)
            run = BeadRun(env, looptest.files(repo), wloop.installs(env.cfgdir, here=self.here), lambda: env.profile().loop, lambda: "",
                          lambda running: None, lambda: None, said.append)
            # the first child is the one that exec'd: its note appears while it runs
            t1 = as_bead({"id": "t-1"})
            assert t1 is not None
            r = run.run(t1, Where("s1", str(self.wt), "sb-1", 0.0))
            leaked = os.environ.get("TL_REEXEC")
        self.assertEqual(r.outcome, "landed")
        self.assertEqual(len(spawned), 2)
        self.assertEqual(spawned[1][:5], procs.script_argv(old / "tl.py"))
        self.assertIsNone(leaked)  # the loop's own environment keeps no hand-over for its later run-tasks
        self.assertEqual(spawned_env[0]["run"], "t-1-20261026-120000")  # the fallback child got it
        self.assertEqual(pids, [str(os.getpid())] * 2)  # run-task's parent is uv: the loop names itself for the lock handoff
        fb = [e for e in self.events() if e["kind"] == "reload_fallback"]
        self.assertEqual([(e["old"], e["new"]) for e in fb], [("0.2.0", "0.1.0")])
        self.assertIn("0.2.0", [e["version"] for e in json.loads((ident.config_dir() / "bad-versions.json").read_text())["entries"]])
        self.assertTrue(any("RED" in c for c in said))
        self.assertFalse(reexec.reexec_path("t-1").exists())

    # -- point 2: delegate is resolved per call, never held
    def test_delegate_route_is_resolved_again_each_call(self):
        c = wslots.load_cfg(str(self.wt))
        with mock.patch.object(
            dl, "resolve", side_effect=[self.res("/a/route.py"), self.res("/b/route.py"), self.res("/b/route.py")]
        ) as fr:
            eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
            self.assertEqual(eng.delegation.route(), "/b/route.py")
            self.assertEqual(eng.delegation.route(), "/b/route.py")
            self.assertEqual(fr.call_count, 3)

    # -- point 4: loop state and dashboard lane
    def test_loop_state_names_the_running_version_and_code_dir(self):
        repo = str(self.wt)
        env = wloop.build(repo, store=FakeBeads(), here=self.here)
        self.assertEqual((env.version, env.code_dir), ("0.1.0", str(self.here)))

    def test_releases_behind_counts_installed_versions_above_it(self):
        for v in ("0.1.0", "0.2.0", "0.10.0"):  # <claude dir>/plugins/cache/<marketplace>/<plugin>/<version>
            main = Path(self.tmp.name, "claude", "plugins", "cache", "m", "iorlas-task-loop", v, "skills", "task-loop", "tl.py")
            main.parent.mkdir(parents=True)
            main.write_text("")
        self.assertEqual(catalog.releases_behind("0.1.0"), 2)
        self.assertEqual(catalog.releases_behind("0.2.0"), 1)
        self.assertEqual(catalog.releases_behind("0.10.0"), 0)

if __name__ == "__main__":
    unittest.main()
