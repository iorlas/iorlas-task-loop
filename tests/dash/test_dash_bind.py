"""tl-bxk.12.5: only the installed plugin copy may serve :7878 or a non-loopback address."""
import contextlib
import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case
from support.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support.narrow import must  # noqa: E402

from taskloop_dash import bind  # noqa: E402
from taskloop_dash.cli import dash as dash_cli  # noqa: E402
from tlkernel import factorydb  # noqa: E402
from tlkernel.env import Env as ProcessEnv  # noqa: E402
from tlkernel.paths import ConfigDir  # noqa: E402
from tlkernel.rowstores import ReposStore  # noqa: E402

TS = "100.64.1.2"  # tailscale-like (CGNAT) address


class Env(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.state = self.home / ".config" / "task-loop"
        self.state.mkdir(parents=True)
        self.dev = Path(self.tmp.name).resolve() / "dev" / "src"
        self.cache = self.home / ".claude" / "plugins" / "cache" / "mkt" / "task-loop" / "1.0" / "src"
        for d in (self.dev, self.cache):  # the rules look at where the code lives
            d.mkdir(parents=True)

    def teardown_method(self):
        self.tmp.cleanup()

    def with_repos(self):
        ReposStore(ConfigDir(self.state)).add(str(self.state), 1.0)

    def run_server(self, where, *args, public=False):
        """`python3 -m taskloop_dash ARGS` for the code in `where`, in this process: a refusal or a failed bind exits, which is all these
        tests start it for -> (exit code, stderr). The env is the child's: no TASK_LOOP_*, its own HOME."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("TASK_LOOP_")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   APPDATA=str(self.home / ".config"))
        if public:
            env["TASK_LOOP_DASH_DEV_PUBLIC"] = "1"
        err = io.StringIO()
        with mock.patch.object(factorydb._STORE, "parts", None), \
                mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err), pytest.raises(SystemExit) as stop:
            dash_cli.main(list(args), here=where)
        return stop.value.code, err.getvalue()

    def guard(self, addrs, port, where=None, **kw):
        return bind.bind_refusal(addrs, port, here=where or self.dev, home=self.home, state=self.state, process=ProcessEnv(), **kw)


class DevCopyRefused(Env):
    def test_port_7878_refused_exit_2(self):
        self.with_repos()
        code, err = self.run_server(self.dev, "--port", "7878", "--bind", "127.0.0.1")
        assert code == 2
        assert "7878" in err
        assert "TASK_LOOP_DASH_DEV_PUBLIC" in err

    def test_wildcard_and_hostnames_are_not_loopback(self):
        for a in ("0.0.0.0", "::", "myhost.local"):
            assert self.guard([a], 0), a

    def test_loopback_random_port_allowed(self):
        for a in ("127.0.0.1", "::1", "localhost"):
            assert self.guard([a], 0) is None, a

    def test_one_bad_address_in_a_list_refuses(self):
        assert self.guard(["127.0.0.1", TS], 0)


class Override(Env):
    def test_env_allows_dev_public_address_and_port(self):
        self.with_repos()
        process = ProcessEnv({"TASK_LOOP_DASH_DEV_PUBLIC": "1"})
        assert bind.bind_refusal([TS], 7878, here=self.dev, home=self.home, state=self.state, process=process) is None


    def test_only_value_1_counts(self):
        process = ProcessEnv({"TASK_LOOP_DASH_DEV_PUBLIC": "0"})
        assert bind.bind_refusal([TS], 0, here=self.dev, home=self.home, state=self.state, process=process)


class InstalledCopy(Env):
    def test_cache_copy_may_bind_tailscale_and_7878(self):
        self.with_repos()
        assert self.guard(["127.0.0.1", TS], 7878, where=self.cache) is None

    def test_symlink_into_cache_does_not_count(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.dev)
        assert self.guard([TS], 0, where=link)

    def test_symlink_out_of_cache_does_not_count(self):
        link = self.home / ".claude" / "plugins" / "cache" / "evil"
        link.symlink_to(self.dev)
        assert self.guard([TS], 0, where=link)

    def test_cache_lookalike_path_does_not_count(self):
        fake = Path(self.tmp.name) / "x" / ".claude" / "plugins" / "cache" / "dash"
        fake.mkdir(parents=True)
        assert self.guard([TS], 0, where=fake)


class EmptyState(Env):
    def test_guard_refuses_installed_copy_too(self):
        assert "no repos registered" in must(self.guard(["127.0.0.1"], 7878, where=self.cache))

    def test_other_port_needs_no_repos_json(self):
        assert self.guard(["127.0.0.1"], 0, where=self.cache) is None
