"""Dashboard launch compatibility and development binding rules."""
from pathlib import Path

from tlkernel.dash import READ_PROTOCOL
from tlkernel.env import Env as ProcessEnv
from tlkernel.factoryparts import PIPELINE
from tltestkit.case import Case
from tltestkit.narrow import must
from tltestkit.tmpdir import TemporaryDirectory

from tldash import bind
from tldash.cli import dash as dash_server

INSTALLED = {"pipeline": PIPELINE.version}


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
        assert dash_server.default_binds(ProcessEnv(), tailscale=lambda: "100.1.2.3") == ["127.0.0.1", "100.1.2.3"]
        assert dash_server.inet_addrs("2: eth0 inet 100.64.0.5/32 scope global\n inet6 fe80::1/64 inet bogus") == ["100.64.0.5"]
