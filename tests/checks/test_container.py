"""Checks that say `"in": "container"`: they run through container_run.py on a fake docker; the result is the host path's."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import PY, EngineTest, no_repo, real_git, real_proc, shq

# isort: split
import os
import threading
from unittest import mock

from support.fakedocker import FakeDocker
from support.waits import until

from taskloop.contracts import config
from taskloop.contracts.paths import RepoDirs

LIST = PY + " -c " + shq("import os; print(sorted(os.listdir('.')))")
WRITE = PY + " -c " + shq(
    "import os; open(os.environ['TL_ARTIFACTS'] + '/p.txt', 'w').write(os.environ['TL_ARTIFACT_STEP']); open('made', 'w'); print('ok')")
BOX = {"image": "img:1"}


@real_proc("container_run.py is a real process driving a fake docker script: the verbs it sends and the stop that kills the container")
class ContainerChecksTest(EngineTest):
    def setUp(self):
        super().setUp()
        self.docker = FakeDocker(Path(self.tmp.name) / "fake-docker", sys.executable)
        env = mock.patch.dict(os.environ, {"PATH": self.docker.path})
        env.start()
        self.addCleanup(env.stop)

    def run_one(self, cmd, boxed=True, **cfg):
        check = {"id": "c", "cmd": cmd, **({"in": "container"} if boxed else {})}
        self.eng = self.checks_engine(checks=[check], container=BOX, **cfg)
        self.warn = mock.Mock()
        self.eng.warn = self.warn
        res = self.eng.run_checks({"checks": [], "files": []}, "s")[0]
        return res, (self.eng.run_dir / res.log).read_text()

    @real_git("the runner lists the worktree with a real git")
    def test_docker_up_runs_in_the_container_with_the_hosts_result(self):
        res, log = self.run_one(WRITE)
        self.assertEqual((res.exit, res.status, res.tail), (0, "passed", "ok"))
        self.assertTrue(log.startswith("in container img:1\n"))
        self.assertIn("run", self.docker.verbs())
        self.assertFalse((self.wt / "made").exists())  # what the check writes inside stays inside
        self.assertEqual((RepoDirs(self.wt).artifacts("t-1") / "p.txt").read_text(), "c")  # $TL_ARTIFACTS comes back
        host, _ = self.run_one(WRITE, boxed=False)
        self.assertEqual(res.model_copy(update={"secs": 0, "log": "", "wall_hit": False}), host.model_copy(update={"secs": 0, "log": ""}))

    @real_git("the runner lists the worktree with a real git")
    def test_docker_down_falls_back_to_the_host_with_one_warning(self):
        self.docker.down()
        res, log = self.run_one(WRITE)
        self.assertEqual((res.exit, res.tail), (0, "ok"))
        self.assertTrue(log.startswith("on host (docker not reachable)\n"))
        self.assertEqual(self.docker.verbs(), ["info"])
        self.assertEqual(len([c for c in self.warn.call_args_list if "docker not reachable" in c.args[0]]), 1)
        self.assertTrue((self.wt / "made").exists())

    def test_a_check_without_in_never_calls_docker(self):
        res, log = self.run_one(WRITE, boxed=False)
        self.assertEqual(res.exit, 0)
        self.assertNotIn("container", log)
        self.assertEqual(self.docker.calls(), [])

    @real_git("the runner lists the worktree with a real git")
    def test_untracked_files_go_in_and_ignored_ones_do_not(self):
        (self.wt / "new.txt").write_text("x\n")
        (self.wt / "skip.log").write_text("x\n")
        (self.wt / ".gitignore").write_text("*.log\n")
        _, log = self.run_one(LIST)
        self.assertIn("'new.txt'", log)
        self.assertNotIn("skip.log", log)

    @real_git("the runner lists the worktree with a real git")
    def test_a_stop_kills_the_named_container(self):
        sleeper = PY + " -c " + shq("import time; time.sleep(60)")
        self.eng = self.checks_engine(checks=[{"id": "c", "cmd": sleeper, "in": "container"}], container=BOX)
        t = threading.Thread(target=lambda: self.eng.run_checks({"checks": [], "files": []}, "s"), daemon=True)
        t.start()
        self.assertTrue(until(lambda: any(p.suffix == ".pid" for p in self.docker.root.iterdir())))
        self.eng.halt.set()
        t.join(30)
        self.assertFalse(t.is_alive())
        kills = [c for c in self.docker.calls() if c[0] == "kill"]
        self.assertEqual(len(kills), 1)
        self.assertTrue(kills[0][1].startswith("tl-check-t-1"))

    @no_repo
    def test_a_bad_container_setting_fails_the_config_load(self):
        for bad in ({"container": {"image": "a", "dockerfile": "b"}}, {"container": {}}, {"container": {"imag": "a"}},
                    {"checks": [{"id": "c", "argv": ["true"], "in": "container"}]},
                    {"container": BOX, "checks": [{"id": "c", "argv": ["true"], "in": "vm"}]}):
            with self.assertRaises(config.ConfigError, msg=str(bad)):
                config.load({"engine": bad})
        got = config.load({"engine": {"container": {"dockerfile": "D"}}}).engine.container
        self.assertEqual(got and got.dockerfile, "D")
