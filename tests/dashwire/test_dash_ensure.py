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
from taskloop.app.launch import dash as dash_server  # noqa: E402
from taskloop.app.parts import STAGE_PARTS  # noqa: E402
from tldash import bind  # noqa: E402
from tlkernel.dash import READ_PROTOCOL  # noqa: E402
from tlkernel.env import Env as ProcessEnv  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.factoryparts import PIPELINE  # noqa: E402
from tltestkit.narrow import must  # noqa: E402

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


class StaleReason(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.script = Path(self.tmp.name) / "server.py"
        self.script.write_text("")

    def teardown_method(self):
        self.tmp.cleanup()

    def test_current_server_is_not_stale(self):
        assert dash_server.stale_reason(live(self.script), "v1", ["127.0.0.1"], INSTALLED) is None

    def test_deleted_script_is_stale(self):
        v = live(Path(self.tmp.name) / "gone" / "server.py")
        assert "gone" in must(dash_server.stale_reason(v, "v1", ["127.0.0.1"], INSTALLED))

    def test_version_differs_is_stale(self):
        assert "version" in must(dash_server.stale_reason(live(self.script, "v0"), "v1", ["127.0.0.1"], INSTALLED))

    def test_a_server_speaking_another_read_protocol_is_stale_even_at_the_same_code_version(self):
        assert "protocol" in must(dash_server.stale_reason(live(self.script, protocol=READ_PROTOCOL + 1), "v1", ["127.0.0.1"], INSTALLED))
        assert "protocol" in must(dash_server.stale_reason(live(self.script, protocol=None), "v1", ["127.0.0.1"], INSTALLED))

    def test_a_server_whose_part_needs_miss_the_installed_version_is_replaced(self):
        version = PIPELINE.version
        for needs, parts, reason in [
            ({"pipeline": version + 1}, {"pipeline": version + 1},
             f"it needs part pipeline v{version + 1}, installed is v{version}"),
            ({"pipeline": 1}, {"pipeline": 0}, f"installed part pipeline is v{version}, it reads up to v0"),
        ]:
            v = dict(live(self.script), needs=needs, parts=parts)
            assert dash_server.stale_reason(v, "v1", ["127.0.0.1"], INSTALLED) == reason
        ok = dict(live(self.script), needs={"pipeline": 1}, parts={"pipeline": PIPELINE.version})
        assert dash_server.stale_reason(ok, "v1", ["127.0.0.1"], INSTALLED) is None

    def test_server_must_report_part_contracts(self):
        for fields in ({"needs": None}, {"parts": None}, {"needs": {"pipeline": "1"}},
                       {"needs": {"pipeline": 1}, "parts": {}}):
            v = dict(live(self.script), **fields)
            assert dash_server.stale_reason(v, "v1", ["127.0.0.1"], INSTALLED) is not None

    def test_missing_address_is_stale(self):
        r = dash_server.stale_reason(live(self.script), "v1", ["127.0.0.1", "100.1.2.3"], INSTALLED)
        assert "100.1.2.3" in must(r)

    def test_extra_address_is_fine(self):
        assert dash_server.stale_reason(live(self.script, binds=("127.0.0.1", "100.1.2.3")), "v1", ["127.0.0.1"], INSTALLED) is None

    def test_old_server_without_script_or_binds_is_stale(self):
        v = live(self.script)
        del v["script"], v["binds"]
        assert dash_server.stale_reason(v, "v1", ["127.0.0.1"], INSTALLED) is not None

    def test_is_task_loop_server_shape(self):
        assert dash_server.is_dash_server(live(self.script))
        assert not dash_server.is_dash_server({"hello": 1})
        assert not dash_server.is_dash_server(None)


class EnsureFlow(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
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
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED)
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
            rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED)
        assert rc == 1
        out = " ".join(str(c.args[0]) for c in pr.call_args_list)
        assert "100.1.2.3" in out
        assert "pid 99" in out

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
                rc = dash_server.run("ensure", snapshot(), spawner=real_spawner(), installed=INSTALLED)
        assert rc == 0
        stop.assert_not_called()
        cmd = popen.call_args.args[0]
        assert cmd[cmd.index("--port") + 1] == "54321"
        assert cmd[cmd.index("--bind") + 1] == "127.0.0.1"
        ping.assert_called_with(54321)


class DevCheckout(Case):
    def test_git_worktree_is_dev(self):
        with TemporaryDirectory() as d:
            (Path(d) / ".git").write_text("gitdir: /x")
            sub = Path(d) / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            assert bind.is_dev_checkout(sub)

    def test_plugin_cache_is_not_dev_even_inside_git(self):
        with TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            sub = Path(d) / "plugins" / "cache" / "mk" / "tl" / "0.17.0" / "skills" / "task-loop" / "dash"
            sub.mkdir(parents=True)
            assert not bind.is_dev_checkout(sub)

    def test_plain_directory_is_not_dev(self):
        with TemporaryDirectory() as d:
            assert not bind.is_dev_checkout(Path(d))

    def test_dev_defaults_to_loopback_random_port(self):
        addrs, port = bind.plan(None, None, dev=True, process=ProcessEnv())
        assert addrs == ["127.0.0.1"]
        assert port == 0

    def test_dev_with_explicit_port_or_bind_is_honoured(self):
        addrs, port = bind.plan(9999, "127.0.0.1,100.9.9.9", dev=True, process=ProcessEnv())
        assert (addrs, port) == (["127.0.0.1", "100.9.9.9"], 9999)
        addrs, port = bind.plan(9999, None, dev=True, process=ProcessEnv())
        assert (addrs, port) == (["127.0.0.1"], 9999)

    def test_the_server_alone_binds_loopback_on_7878_and_the_launcher_adds_tailscale(self):
        assert bind.plan(None, None, dev=False, process=ProcessEnv()) == (["127.0.0.1"], 7878)  # the server runs no network tool
        with mock.patch.object(dash_server, "tailscale_ip", return_value="100.1.2.3"):
            assert dash_server.default_binds(ProcessEnv(), spawner=real_spawner()) == ["127.0.0.1", "100.1.2.3"]
        assert dash_server.inet_addrs("2: eth0 inet 100.64.0.5/32 scope global\n inet6 fe80::1/64 inet bogus") == ["100.64.0.5"]
