"""Checks that say `"in": "container"`: they run through container_run.py on a recorder that stands for docker (no docker anywhere);
the result is the host path's."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EngineTest, no_repo

# isort: split
import os
from unittest import mock

from support import procsim
from support.fakedocker import FakeDocker

from taskloop.contracts import config


def listing(cwd, env):
    return 0, str(sorted(os.listdir(cwd)))


def write(cwd, env):
    (Path(env["TL_ARTIFACTS"]) / "p.txt").write_text(env["TL_ARTIFACT_STEP"])
    (cwd / "made").write_text("")
    return 0, "ok"


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


    def test_a_check_without_in_never_calls_docker(self):
        res, log = self.run_one(WRITE, boxed=False)
        self.assertEqual(res.exit, 0)
        self.assertNotIn("container", log)
        self.assertEqual(self.docker.calls, [])


    @no_repo
    def test_a_bad_container_setting_fails_the_config_load(self):
        for bad in ({"container": {"image": "a", "dockerfile": "b"}}, {"container": {}}, {"container": {"imag": "a"}},
                    {"checks": [{"id": "c", "argv": ["true"], "in": "container"}]},
                    {"container": BOX, "checks": [{"id": "c", "argv": ["true"], "in": "vm"}]}):
            with self.assertRaises(config.ConfigError, msg=str(bad)):
                config.load({"engine": bad})
        got = config.load({"engine": {"container": {"dockerfile": "D"}}}).engine.container
        self.assertEqual(got and got.dockerfile, "D")
