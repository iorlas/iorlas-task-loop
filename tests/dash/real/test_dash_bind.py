"""tl-bxk.12.5: only the installed plugin copy may serve :7878 or a non-loopback address."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

from taskloop_dash import bind  # noqa: E402
from taskloop_dash.cli import dash as dash_cli  # noqa: E402


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.state = self.home / ".config" / "task-loop"
        self.state.mkdir(parents=True)
        self.dev = Path(self.tmp.name).resolve() / "dev" / "src"
        self.cache = self.home / ".claude" / "plugins" / "cache" / "mkt" / "task-loop" / "1.0" / "src"
        for d in (self.dev, self.cache):  # the rules look at where the code lives
            d.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def with_repos(self):
        (self.state / "repos.json").write_text("{}")

    def run_server(self, where, *args, public=False):
        """`python3 -m taskloop_dash ARGS` for the code in `where`, in this process: a refusal or a failed bind exits, which is all these
        tests start it for -> (exit code, stderr). The env is the child's: no TASK_LOOP_*, its own HOME."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("TASK_LOOP_")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   APPDATA=str(self.home / ".config"))
        if public:
            env["TASK_LOOP_DASH_DEV_PUBLIC"] = "1"
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            dash_cli.main(list(args), here=where)
        return stop.exception.code, err.getvalue()

    def guard(self, addrs, port, where=None, **kw):
        os.environ.pop("TASK_LOOP_DASH_DEV_PUBLIC", None)
        return bind.bind_refusal(addrs, port, here=where or self.dev, home=self.home, state=self.state, **kw)


class Override(Env):

    def test_the_server_override_gets_past_the_rule(self):
        # TEST-NET-1 address cannot be bound: the bind itself fails, proving the rule let it through
        code, err = self.run_server(self.dev, "--bind", "192.0.2.1", "--port", "0", public=True)
        self.assertEqual(code, 2)
        self.assertIn("bind 192.0.2.1", err)


if __name__ == "__main__":
    unittest.main()
