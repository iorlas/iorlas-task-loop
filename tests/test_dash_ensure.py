"""tl-bxk.12.4: dash ensure replaces stale servers, binds fail loudly, dev checkouts stay on loopback."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402
import tl  # noqa: E402

SERVER = ROOT / "skills" / "task-loop" / "dash" / "server.py"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def live(script, version="v1", binds=("127.0.0.1",), pid=4242):
    return {"version": version, "pid": pid, "script": str(script), "binds": list(binds),
            "urls": ["http://%s:7878" % b for b in binds], "started": 1.0}


class StaleReason(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.script = Path(self.tmp.name) / "server.py"
        self.script.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def test_current_server_is_not_stale(self):
        self.assertIsNone(tl.stale_reason(live(self.script), "v1", ["127.0.0.1"]))

    def test_deleted_script_is_stale(self):
        v = live(Path(self.tmp.name) / "gone" / "server.py")
        self.assertIn("gone", tl.stale_reason(v, "v1", ["127.0.0.1"]))

    def test_version_differs_is_stale(self):
        self.assertIn("version", tl.stale_reason(live(self.script, "v0"), "v1", ["127.0.0.1"]))

    def test_missing_address_is_stale(self):
        r = tl.stale_reason(live(self.script), "v1", ["127.0.0.1", "100.1.2.3"])
        self.assertIn("100.1.2.3", r)

    def test_extra_address_is_fine(self):
        self.assertIsNone(tl.stale_reason(live(self.script, binds=("127.0.0.1", "100.1.2.3")), "v1", ["127.0.0.1"]))

    def test_old_server_without_script_or_binds_is_stale(self):
        v = live(self.script)
        del v["script"], v["binds"]
        self.assertIsNotNone(tl.stale_reason(v, "v1", ["127.0.0.1"]))

    def test_is_task_loop_server_shape(self):
        self.assertTrue(tl.is_dash_server(live(self.script)))
        self.assertFalse(tl.is_dash_server({"hello": 1}))
        self.assertFalse(tl.is_dash_server(None))


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
                          ("is_dev_checkout", False)):
            q = mock.patch.object(tl, name, (lambda v=val: (lambda *a: v))() if name != "is_dev_checkout" else (lambda: val))
            q.start()
            self.addCleanup(q.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_ensure(self, pings):
        stops, popens = [], []
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(tl, "ping", side_effect=pings), \
                mock.patch.object(tl, "stop_server", side_effect=lambda v=None: stops.append(v)), \
                mock.patch.object(tl.subprocess, "Popen", side_effect=lambda *a, **k: popens.append(a) or proc), \
                mock.patch.object(tl.time, "sleep"):
            rc = tl.cmd_dash(mock.Mock(op="ensure"))
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
        with mock.patch.object(tl, "ping", return_value=None), \
                mock.patch.object(tl.subprocess, "Popen", return_value=proc), \
                mock.patch.object(tl, "log_tail", return_value="bind 100.1.2.3:7878 failed (held by pid 99)"), \
                mock.patch.object(tl.time, "sleep"), \
                mock.patch("builtins.print") as pr:
            rc = tl.cmd_dash(mock.Mock(op="ensure"))
        self.assertEqual(rc, 1)
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("100.1.2.3", out)
        self.assertIn("pid 99", out)

    def test_dev_checkout_ensure_never_touches_the_installed_port(self):
        os.environ.pop("TASK_LOOP_DASH_PORT")
        with mock.patch.object(tl, "is_dev_checkout", return_value=True), \
                mock.patch.object(tl, "free_port", return_value=54321):
            ping = mock.Mock(return_value=live(self.script, binds=("127.0.0.1",)))
            stop = mock.Mock()
            proc = mock.Mock()
            proc.poll.return_value = None
            with mock.patch.object(tl, "ping", ping), mock.patch.object(tl, "stop_server", stop), \
                    mock.patch.object(tl.subprocess, "Popen", return_value=proc) as popen, \
                    mock.patch.object(tl.time, "sleep"):
                rc = tl.cmd_dash(mock.Mock(op="ensure"))
        self.assertEqual(rc, 0)
        stop.assert_not_called()
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--port") + 1], "54321")
        self.assertEqual(cmd[cmd.index("--bind") + 1], "127.0.0.1")
        ping.assert_called_with(54321)


class LoudBind(unittest.TestCase):
    def test_open_servers_fails_on_any_address(self):
        port = free_port()
        with self.assertRaises(server.BindError) as cm:
            server.open_servers(["127.0.0.1", "203.0.113.9"], port, mock.Mock())
        self.assertIn("203.0.113.9:%d" % port, str(cm.exception))

    def test_open_servers_names_the_holder_pid(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        try:
            with self.assertRaises(server.BindError) as cm:
                server.open_servers(["127.0.0.1"], port, mock.Mock())
        finally:
            holder.close()
        self.assertIn("127.0.0.1:%d" % port, str(cm.exception))
        self.assertIn("pid %d" % os.getpid(), str(cm.exception))

    def test_open_servers_closes_earlier_sockets_on_failure(self):
        port = free_port()
        with self.assertRaises(server.BindError):
            server.open_servers(["127.0.0.1", "203.0.113.9"], port, mock.Mock())
        s = socket.socket()
        s.bind(("127.0.0.1", port))  # would raise if the first server were left open
        s.close()

    def test_process_exits_nonzero_and_serves_nothing(self):
        port = free_port()
        r = subprocess.run([sys.executable, str(SERVER), "--port", str(port), "--bind", "127.0.0.1,203.0.113.9"],
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, "TASK_LOOP_DASH_DEV_PUBLIC": "1", "XDG_CONFIG_HOME": tempfile.mkdtemp(), "APPDATA": tempfile.mkdtemp()})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("203.0.113.9:%d" % port, r.stderr)
        s = socket.socket()
        self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0)
        s.close()


class DevCheckout(unittest.TestCase):
    def test_git_worktree_is_dev(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").write_text("gitdir: /x")
            sub = Path(d) / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            self.assertTrue(server.is_dev_checkout(sub))

    def test_plugin_cache_is_not_dev_even_inside_git(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            sub = Path(d) / "plugins" / "cache" / "mk" / "tl" / "0.17.0" / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            self.assertFalse(server.is_dev_checkout(sub))

    def test_plain_directory_is_not_dev(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(server.is_dev_checkout(Path(d)))

    def test_dev_defaults_to_loopback_random_port(self):
        with mock.patch.object(server, "tailscale_ip", return_value="100.1.2.3"), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TASK_LOOP_DASH_BIND", None)
            addrs, port = server.plan(None, None, dev=True)
        self.assertEqual(addrs, ["127.0.0.1"])
        self.assertEqual(port, 0)

    def test_dev_with_explicit_port_or_bind_is_honoured(self):
        addrs, port = server.plan(9999, "127.0.0.1,100.9.9.9", dev=True)
        self.assertEqual((addrs, port), (["127.0.0.1", "100.9.9.9"], 9999))
        addrs, port = server.plan(9999, None, dev=True)
        self.assertEqual((addrs, port), (["127.0.0.1"], 9999))

    def test_installed_defaults_unchanged(self):
        with mock.patch.object(server, "tailscale_ip", return_value="100.1.2.3"):
            os.environ.pop("TASK_LOOP_DASH_BIND", None)
            addrs, port = server.plan(None, None, dev=False)
        self.assertEqual((addrs, port), (["127.0.0.1", "100.1.2.3"], 7878))

    def test_dev_server_process_listens_on_random_loopback_port(self):
        cfg = tempfile.mkdtemp()
        p = subprocess.Popen([sys.executable, str(SERVER)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env={**os.environ, "XDG_CONFIG_HOME": cfg, "APPDATA": cfg, "TASK_LOOP_DASH_BIND": ""})
        try:
            first = p.stdout.readline()
            self.assertIn("127.0.0.1:", first)
            self.assertNotIn(":7878", first)
            self.assertNotIn("100.", first)
        finally:
            p.terminate()
            p.wait(5)
            if p.stdout:
                p.stdout.close()
            if p.stderr:
                p.stderr.close()
        # a dev server must not claim the shared pid file
        self.assertFalse((Path(cfg) / "task-loop" / "dash.pid").exists())


if __name__ == "__main__":
    unittest.main()
