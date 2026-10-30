"""tl-bxk.12.4: dash ensure replaces stale servers, binds fail loudly, dev checkouts stay on loopback."""
import gc
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

# isort: split
from support.narrow import must  # noqa: E402
from support.spawn import real_spawner  # noqa: E402

from taskloop.adapters import procs  # noqa: E402
from taskloop.app.launch import dash as dash_server  # noqa: E402
from taskloop.contracts.env import Env as ProcessEnv  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402
from taskloop_dash import bind  # noqa: E402


def _const(value):
    return lambda *a, **k: value


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def live(script, version="v1", binds=("127.0.0.1",), pid=4242):
    return {"version": version, "pid": pid, "script": str(script), "binds": list(binds),
            "urls": [f"http://{b}:7878" for b in binds], "started": 1.0}


class StaleReason(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name) / "server.py"
        self.script.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def test_current_server_is_not_stale(self):
        self.assertIsNone(dash_server.stale_reason(live(self.script), "v1", ["127.0.0.1"]))

    def test_deleted_script_is_stale(self):
        v = live(Path(self.tmp.name) / "gone" / "server.py")
        self.assertIn("gone", must(dash_server.stale_reason(v, "v1", ["127.0.0.1"])))

    def test_version_differs_is_stale(self):
        self.assertIn("version", must(dash_server.stale_reason(live(self.script, "v0"), "v1", ["127.0.0.1"])))

    def test_missing_address_is_stale(self):
        r = dash_server.stale_reason(live(self.script), "v1", ["127.0.0.1", "100.1.2.3"])
        self.assertIn("100.1.2.3", must(r))

    def test_extra_address_is_fine(self):
        self.assertIsNone(dash_server.stale_reason(live(self.script, binds=("127.0.0.1", "100.1.2.3")), "v1", ["127.0.0.1"]))

    def test_old_server_without_script_or_binds_is_stale(self):
        v = live(self.script)
        del v["script"], v["binds"]
        self.assertIsNotNone(dash_server.stale_reason(v, "v1", ["127.0.0.1"]))

    def test_is_task_loop_server_shape(self):
        self.assertTrue(dash_server.is_dash_server(live(self.script)))
        self.assertFalse(dash_server.is_dash_server({"hello": 1}))
        self.assertFalse(dash_server.is_dash_server(None))


class EnsureFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name) / "server.py"
        self.script.write_text("")
        env = {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name, "TASK_LOOP_DASH_PORT": "7878"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for name, val in (("code_version", "v1"), ("expected_binds", ["127.0.0.1", "100.1.2.3"]),
                          ("is_dev_checkout", False), ("tailscale_ip", None)):
            q = mock.patch.object(dash_server, name, (lambda v=val: v) if name == "is_dev_checkout" else _const(val))
            q.start()
            self.addCleanup(q.stop)

    def tearDown(self):
        # dash_server.run leaves dash.log open; the mocked Popen keeps it alive in a cycle, and Windows will not delete an open file
        gc.collect()
        self.tmp.cleanup()

    def run_ensure(self, pings):
        stops, popens = [], []
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(dash_server, "ping", side_effect=pings), \
                mock.patch.object(dash_server, "stop_server", side_effect=lambda v=None, *a, **k: stops.append(v)), \
                mock.patch.object(procs, "spawn", side_effect=lambda *a, **k: popens.append(a) or proc), \
                mock.patch.object(dash_server.time, "sleep"):
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner())
        return rc, stops, popens

    def test_current_server_is_kept(self):
        v = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([v])
        self.assertEqual((rc, stops, popens), (0, [], []))

    def test_server_missing_tailscale_bind_is_replaced(self):
        old = live(self.script)
        new = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([old, None, new])
        self.assertEqual(rc, 0)
        self.assertEqual(stops, [old])
        self.assertEqual(len(popens), 1)

    def test_deleted_worktree_server_is_replaced(self):
        old = live(Path(self.tmp.name) / "wt" / "server.py", binds=("127.0.0.1", "100.1.2.3"))
        new = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([old, None, new])
        self.assertEqual((rc, stops, len(popens)), (0, [old], 1))

    def test_foreign_listener_is_never_stopped(self):
        rc, stops, popens = self.run_ensure([{"hello": "world"}])
        self.assertEqual((rc, stops, popens), (1, [], []))

    def test_start_failure_is_reported_with_log(self):
        proc = mock.Mock()
        proc.poll.return_value = 2
        (Path(self.tmp.name) / "task-loop").mkdir(exist_ok=True)
        with mock.patch.object(dash_server, "ping", return_value=None), \
                mock.patch.object(procs, "spawn", return_value=proc), \
                mock.patch.object(dash_server, "log_tail", return_value="bind 100.1.2.3:7878 failed (held by pid 99)"), \
                mock.patch.object(dash_server.time, "sleep"), \
                mock.patch("builtins.print") as pr:
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner())
        self.assertEqual(rc, 1)
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("100.1.2.3", out)
        self.assertIn("pid 99", out)

    def test_dev_checkout_ensure_never_touches_the_installed_port(self):
        os.environ.pop("TASK_LOOP_DASH_PORT")
        with mock.patch.object(dash_server, "is_dev_checkout", return_value=True), \
                mock.patch.object(dash_server, "free_port", return_value=54321):
            ping = mock.Mock(return_value=live(self.script, binds=("127.0.0.1",)))
            stop = mock.Mock()
            proc = mock.Mock()
            proc.poll.return_value = None
            with mock.patch.object(dash_server, "ping", ping), mock.patch.object(dash_server, "stop_server", stop), \
                    mock.patch.object(procs, "spawn", return_value=proc) as popen, \
                    mock.patch.object(dash_server.time, "sleep"):
                rc = dash_server.run("ensure", snapshot(), spawner=real_spawner())
        self.assertEqual(rc, 0)
        stop.assert_not_called()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--port") + 1], "54321")
        self.assertEqual(cmd[cmd.index("--bind") + 1], "127.0.0.1")
        ping.assert_called_with(54321)


class DevCheckout(unittest.TestCase):
    def test_git_worktree_is_dev(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").write_text("gitdir: /x")
            sub = Path(d) / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            self.assertTrue(bind.is_dev_checkout(sub))

    def test_plugin_cache_is_not_dev_even_inside_git(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            sub = Path(d) / "plugins" / "cache" / "mk" / "tl" / "0.17.0" / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            self.assertFalse(bind.is_dev_checkout(sub))

    def test_plain_directory_is_not_dev(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(bind.is_dev_checkout(Path(d)))

    def test_dev_defaults_to_loopback_random_port(self):
        addrs, port = bind.plan(None, None, dev=True, process=ProcessEnv())
        self.assertEqual(addrs, ["127.0.0.1"])
        self.assertEqual(port, 0)

    def test_dev_with_explicit_port_or_bind_is_honoured(self):
        addrs, port = bind.plan(9999, "127.0.0.1,100.9.9.9", dev=True, process=ProcessEnv())
        self.assertEqual((addrs, port), (["127.0.0.1", "100.9.9.9"], 9999))
        addrs, port = bind.plan(9999, None, dev=True, process=ProcessEnv())
        self.assertEqual((addrs, port), (["127.0.0.1"], 9999))

    def test_the_server_alone_binds_loopback_on_7878_and_the_launcher_adds_tailscale(self):
        self.assertEqual(bind.plan(None, None, dev=False, process=ProcessEnv()), (["127.0.0.1"], 7878))  # the server runs no network tool
        with mock.patch.object(dash_server, "tailscale_ip", return_value="100.1.2.3"):
            self.assertEqual(dash_server.default_binds(ProcessEnv(), spawner=real_spawner()), ["127.0.0.1", "100.1.2.3"])
        self.assertEqual(dash_server.inet_addrs("2: eth0 inet 100.64.0.5/32 scope global\n inet6 fe80::1/64 inet bogus"), ["100.64.0.5"])


if __name__ == "__main__":
    unittest.main()
