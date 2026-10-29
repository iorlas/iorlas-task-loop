"""dev/suite-docker.py: without a reachable docker it warns once and runs the host suite."""
import importlib.util
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from support.narrow import must
from support.procsim import real_proc

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("suite_docker", ROOT / "dev" / "suite-docker.py")
sd = importlib.util.module_from_spec(must(spec))
must(must(spec).loader).exec_module(sd)


class SuiteDocker(unittest.TestCase):
    def test_no_docker_falls_back_to_the_host_suite_with_one_warning(self):
        with mock.patch.object(sd, "docker_ok", return_value=False), mock.patch.object(sd.stream_proc, "run") as run, \
                mock.patch("sys.stderr") as err:
            run.return_value.returncode = 3
            self.assertEqual(sd.main(["--repo", "x"]), 3)
        self.assertEqual(run.call_args[0][0][:5], ["uv", "run", "--quiet", "--script", str(ROOT / "dev" / "suite.py")])
        warned = "".join(c.args[0] for c in err.write.call_args_list)
        self.assertEqual(warned.count("WARNING"), 1)

    @real_proc("a SIGTERM to the real suite-docker.py must remove the real named container")
    def test_sigterm_removes_the_named_container(self):
        if not sd.docker_ok():  # asked here, not at import: collecting the suite starts no docker
            self.skipTest("needs a reachable docker")
        env = dict(os.environ, TASK_LOOP_SUITE_INSIDE="cat >/dev/null; sleep 300")
        p = subprocess.Popen([sys.executable, str(ROOT / "dev" / "suite-docker.py"), "--repo", str(ROOT)], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        name = f"tl-suite-{p.pid}-"

        def containers():
            r = subprocess.run(["docker", "ps", "-q", "--filter", "name=" + name], capture_output=True, text=True, check=False)
            return r.stdout.split()
        for _ in range(300):
            if containers():
                break
            time.sleep(0.1)
        self.assertTrue(containers(), "the container never started")
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=20)
        for _ in range(50):
            if not containers():
                break
            time.sleep(0.1)
        self.assertEqual(containers(), [])


if __name__ == "__main__":
    unittest.main()
