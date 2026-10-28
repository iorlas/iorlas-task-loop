"""tl-bxk.12.5: only the installed plugin copy may serve :7878 or a non-loopback address."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "skills" / "task-loop" / "dash"
sys.path.insert(0, str(DASH))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from taskloop_dash import bind  # noqa: E402

TS = "100.64.1.2"  # tailscale-like (CGNAT) address


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.state = self.home / ".config" / "task-loop"
        self.state.mkdir(parents=True)
        self.dev = Path(self.tmp.name).resolve() / "dev" / "dash"
        self.cache = self.home / ".claude" / "plugins" / "cache" / "mkt" / "task-loop" / "1.0" / "dash"
        for d in (self.dev, self.cache):
            shutil.copytree(DASH, d, ignore=shutil.ignore_patterns("__pycache__"))

    def tearDown(self):
        self.tmp.cleanup()

    def with_repos(self):
        (self.state / "repos.json").write_text("{}")

    def run_server(self, where, *args, public=False):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TASK_LOOP_")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   APPDATA=str(self.home / ".config"), PYTHONPATH=str(ROOT / "src"))  # a copied dash/ has no src/ beside it
        if public:
            env["TASK_LOOP_DASH_DEV_PUBLIC"] = "1"
        return subprocess.run([sys.executable, str(where / "server.py"), *args], env=env,
                              capture_output=True, text=True, timeout=20)

    def guard(self, addrs, port, where=None, **kw):
        os.environ.pop("TASK_LOOP_DASH_DEV_PUBLIC", None)
        return bind.bind_refusal(addrs, port, here=where or self.dev, home=self.home, state=self.state, **kw)


class DevCopyRefused(Env):
    def test_port_7878_refused_exit_2(self):
        self.with_repos()
        r = self.run_server(self.dev, "--port", "7878", "--bind", "127.0.0.1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("7878", r.stderr)
        self.assertIn("TASK_LOOP_DASH_DEV_PUBLIC", r.stderr)

    def test_tailscale_bind_refused_exit_2(self):
        r = self.run_server(self.dev, "--bind", TS, "--port", "0")
        self.assertEqual(r.returncode, 2)
        self.assertIn(TS, r.stderr)
        self.assertNotIn("failed", r.stderr)  # refused by the rule, never attempted

    def test_wildcard_and_hostnames_are_not_loopback(self):
        for a in ("0.0.0.0", "::", "myhost.local"):
            self.assertTrue(self.guard([a], 0), a)

    def test_loopback_random_port_allowed(self):
        for a in ("127.0.0.1", "::1", "localhost"):
            self.assertIsNone(self.guard([a], 0), a)

    def test_one_bad_address_in_a_list_refuses(self):
        self.assertTrue(self.guard(["127.0.0.1", TS], 0))


class Override(Env):
    def test_env_allows_dev_public_address_and_port(self):
        self.with_repos()
        os.environ["TASK_LOOP_DASH_DEV_PUBLIC"] = "1"
        try:
            self.assertIsNone(bind.bind_refusal([TS], 7878, here=self.dev, home=self.home, state=self.state))
        finally:
            os.environ.pop("TASK_LOOP_DASH_DEV_PUBLIC")

    def test_subprocess_override_gets_past_the_rule(self):
        # TEST-NET-1 address cannot be bound: the bind itself fails, proving the rule let it through
        r = self.run_server(self.dev, "--bind", "192.0.2.1", "--port", "0", public=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bind 192.0.2.1", r.stderr)

    def test_only_value_1_counts(self):
        os.environ["TASK_LOOP_DASH_DEV_PUBLIC"] = "0"
        try:
            self.assertTrue(bind.bind_refusal([TS], 0, here=self.dev, home=self.home, state=self.state))
        finally:
            os.environ.pop("TASK_LOOP_DASH_DEV_PUBLIC")


class InstalledCopy(Env):
    def test_cache_copy_may_bind_tailscale_and_7878(self):
        self.with_repos()
        self.assertIsNone(self.guard(["127.0.0.1", TS], 7878, where=self.cache))

    def test_symlink_into_cache_does_not_count(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.dev)
        self.assertTrue(self.guard([TS], 0, where=link))

    def test_symlink_out_of_cache_does_not_count(self):
        link = self.home / ".claude" / "plugins" / "cache" / "evil"
        link.symlink_to(self.dev)
        self.assertTrue(self.guard([TS], 0, where=link))

    def test_cache_lookalike_path_does_not_count(self):
        fake = Path(self.tmp.name) / "x" / ".claude" / "plugins" / "cache" / "dash"
        fake.mkdir(parents=True)
        self.assertTrue(self.guard([TS], 0, where=fake))


class EmptyState(Env):
    def test_7878_without_repos_json_refused_exit_2(self):
        r = self.run_server(self.cache, "--port", "7878", "--bind", "127.0.0.1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("repos.json", r.stderr)

    def test_guard_refuses_installed_copy_too(self):
        self.assertIn("repos.json", self.guard(["127.0.0.1"], 7878, where=self.cache))

    def test_other_port_needs_no_repos_json(self):
        self.assertIsNone(self.guard(["127.0.0.1"], 0, where=self.cache))


if __name__ == "__main__":
    unittest.main()
