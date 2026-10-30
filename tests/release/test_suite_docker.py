"""dev/suite-docker.py: without a reachable docker it warns once and runs the host suite."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

from support.narrow import must

ROOT = Path(__file__).resolve().parents[2]
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


if __name__ == "__main__":
    unittest.main()
