"""Checks that say `"in": "container"`: they run through container_run.py on a recorder that stands for docker (no docker anywhere);
the result is the host path's."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest, real_git

# isort: split
import os
import signal
from unittest import mock

from support import procsim
from support.fakedocker import FakeDocker

from taskloop.app.checks import container_run
from taskloop.contracts.paths import RepoDirs


def listing(cwd, env):
    return 0, str(sorted(os.listdir(cwd)))


def write(cwd, env):
    (Path(env["TL_ARTIFACTS"]) / "p.txt").write_text(env["TL_ARTIFACT_STEP"])
    (cwd / "made").write_text("")
    return 0, "ok"


LIST = procsim.default("box-list", listing)
WRITE = procsim.default("box-write", write)
BOX = {"image": "img:1"}


class ContainerChecksTest(EngineTest):
    def setUp(self):
        super().setUp()
        self.docker = FakeDocker(Path(self.tmp.name) / "fake-docker")
        self.docker.install(self)

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
        self.assertEqual(res.replace(secs=0, log="", wall_hit=False), host.replace(secs=0, log=""))

    @real_git("the runner lists the worktree with a real git")
    def test_docker_down_falls_back_to_the_host_with_one_warning(self):
        self.docker.down()
        res, log = self.run_one(WRITE)
        self.assertEqual((res.exit, res.tail), (0, "ok"))
        self.assertTrue(log.startswith("on host (docker not reachable)\n"))
        self.assertEqual(self.docker.verbs(), ["info"])
        self.assertEqual(len([c for c in self.warn.call_args_list if "docker not reachable" in c.args[0]]), 1)
        self.assertTrue((self.wt / "made").exists())


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
        """The stop reaches the runner as SIGTERM while it waits on `docker run`: its handler (called here from inside the wait)
        kills the container by its name and exits 128+15."""
        handlers = {}
        self.docker.on_wait = lambda name: handlers[signal.SIGTERM](signal.SIGTERM, None)
        name = "tl-check-t-1-c"
        with mock.patch.object(container_run.signal, "signal", handlers.setdefault), \
                mock.patch("os.getcwd", return_value=str(self.wt)), self.assertRaises(SystemExit) as stop:
            container_run.main(["--image", "img:1", "--name", name, "--", "box-list"])
        self.assertEqual(stop.exception.code, 128 + signal.SIGTERM)
        self.assertEqual([c for c in self.docker.calls if c[0] == "kill"], [["kill", name]])

