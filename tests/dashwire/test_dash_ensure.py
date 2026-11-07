"""tl-bxk.12.4: dash ensure replaces stale servers, binds fail loudly, dev checkouts stay on loopback."""
import gc
import os
import socket
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
from support.spawn import real_spawner  # noqa: E402

from taskloop.adapters import procs  # noqa: E402
from taskloop.app.parts import STAGE_PARTS  # noqa: E402
from tldash.cli import dash as dash_server  # noqa: E402
from tlkernel.dash import READ_PROTOCOL  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.factoryparts import PIPELINE  # noqa: E402

INSTALLED = {p.name: p.version for p in STAGE_PARTS}


def _const(value):
    return lambda *a, **k: value


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def live(script, version="v1", binds=("127.0.0.1",), pid=4242, protocol=READ_PROTOCOL):
    return {"version": version, "pid": pid, "script": str(script), "binds": list(binds),
            "urls": [f"http://{b}:7878" for b in binds], "started": 1.0, "protocol": protocol,
            "needs": {"pipeline": 1}, "parts": {"pipeline": PIPELINE.version}}


class EnsureFlow(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.script = Path(self.tmp.name) / "server.py"
        self.script.write_text("")
        (Path(self.tmp.name) / "task-loop").mkdir()
        env = {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name, "TASK_LOOP_DASH_PORT": "7878"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        for name, val in (("code_version", "v1"), ("expected_binds", ["127.0.0.1", "100.1.2.3"]),
                          ("tailscale_ip", None)):
            q = mock.patch.object(dash_server, name, _const(val))
            q.start()
            self.addCleanup(q.stop)

    def teardown_method(self):
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
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED,
                                 root=ROOT, home=Path(self.tmp.name) / "task-loop")
        return rc, stops, popens

    def test_current_server_is_kept(self):
        v = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([v])
        assert (rc, stops, popens) == (0, [], [])

    def test_an_old_token_file_is_deleted(self):
        tok = Path(self.tmp.name) / "task-loop" / "dash.token"
        tok.parent.mkdir(parents=True, exist_ok=True)
        tok.write_text("old")
        self.run_ensure([live(self.script, binds=("127.0.0.1", "100.1.2.3"))])
        assert not tok.exists()

    def test_server_missing_tailscale_bind_is_replaced(self):
        old = live(self.script)
        new = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([old, None, new])
        assert rc == 0
        assert stops == [old]
        assert len(popens) == 1

    def test_deleted_worktree_server_is_replaced(self):
        old = live(Path(self.tmp.name) / "wt" / "server.py", binds=("127.0.0.1", "100.1.2.3"))
        new = live(self.script, binds=("127.0.0.1", "100.1.2.3"))
        rc, stops, popens = self.run_ensure([old, None, new])
        assert (rc, stops, len(popens)) == (0, [old], 1)

    def test_foreign_listener_is_never_stopped(self):
        rc, stops, popens = self.run_ensure([{"hello": "world"}])
        assert (rc, stops, popens) == (1, [], [])

    def test_start_failure_is_reported_with_log(self):
        proc = mock.Mock()
        proc.poll.return_value = 2
        (Path(self.tmp.name) / "task-loop").mkdir(exist_ok=True)
        with mock.patch.object(dash_server, "ping", return_value=None), \
                mock.patch.object(procs, "spawn", return_value=proc), \
                mock.patch.object(dash_server, "log_tail", return_value="bind 100.1.2.3:7878 failed (held by pid 99)"), \
                mock.patch.object(dash_server.time, "sleep"), \
                mock.patch("builtins.print") as pr:
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED,
                                 root=ROOT, home=Path(self.tmp.name) / "task-loop")
        assert rc == 1
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        assert "100.1.2.3" in out
        assert "pid 99" in out

    def test_dev_checkout_ensure_never_touches_the_installed_port(self):
        os.environ.pop("TASK_LOOP_DASH_PORT")
        with mock.patch.object(dash_server.dash_bind, "is_dev_checkout", return_value=True), \
                mock.patch.object(dash_server, "free_port", return_value=54321):
            ping = mock.Mock(return_value=live(self.script, binds=("127.0.0.1",)))
            stop = mock.Mock()
            proc = mock.Mock()
            proc.poll.return_value = None
            with mock.patch.object(dash_server, "ping", ping), mock.patch.object(dash_server, "stop_server", stop), \
                    mock.patch.object(procs, "spawn", return_value=proc) as popen, \
                    mock.patch.object(dash_server.time, "sleep"):
                rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED,
                                 root=ROOT, home=Path(self.tmp.name) / "task-loop")
        assert rc == 0
        stop.assert_not_called()
        cmd = popen.call_args.args[0]
        assert cmd[cmd.index("--port") + 1] == "54321"
        assert cmd[cmd.index("--bind") + 1] == "127.0.0.1"
        ping.assert_called_with(54321)
