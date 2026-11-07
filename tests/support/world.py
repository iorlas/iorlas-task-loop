"""The world a slot test runs in: temp dir, process env, gitsim (or a real origin + clone), and nothing of the engine."""
import atexit
import contextlib
import os
import shlex
import shutil
from pathlib import Path
from unittest import mock

import pytest
from jsonl_log import close_held

from support import gitsim, procsim
from support.checked import run_checked
from support.waits import until
from taskloop.adapters import halt as halting
from taskloop.adapters import ident
from tlkernel.argv import text_of
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory, mkdtemp

# Engine.MARKERS; tests/checks/test_check_host_contract.py holds them equal
MARKERS = text_of(["python3", str(ident.PLUGIN_ROOT / "src" / "taskloop" / "adapters" / "markers.py")])

_TEMPLATE = []
# No background git: a push's receive-pack and a commit run `gc --auto` / `maintenance run --auto` detached, writing into the
# repo (objects/maintenance.lock) while a test copytrees it. Env covers every git call, repo config covers the rest.
NO_GC = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
         "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}


def _template():
    """origin (o.git) + clone (wt) with one pushed commit, built once per process: on a machine where every new file and
    process costs 5-30 ms (Defender) a copy is ~4x cheaper than the 5 git calls that make it."""
    if not _TEMPLATE:
        d = Path(mkdtemp(prefix="tl-engine-template-"))
        atexit.register(shutil.rmtree, d, True)
        env = {**os.environ, **NO_GC}
        env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        def g(*a, cwd):
            run_checked(list(a), cwd, env=env)
        g("git", "init", "-q", "--bare", "-b", "main", str(d / "o.git"), cwd=d)
        g("git", "clone", "-q", str(d / "o.git"), str(d / "wt"), cwd=d)
        for repo in ("o.git", "wt"):
            g("git", "config", "maintenance.auto", "false", cwd=d / repo)
            g("git", "config", "gc.auto", "0", cwd=d / repo)
        (d / "wt" / "a.txt").write_text("a\n")
        g("git", "add", "-A", cwd=d / "wt")
        g("git", "commit", "-qm", "init", cwd=d / "wt")
        g("git", "push", "-q", "origin", "HEAD:main", cwd=d / "wt")
        _TEMPLATE.append(d)
    return _TEMPLATE[0]


def copy_origin_and_clone(home):
    """Put a fresh o.git and wt in `home` (what five git calls used to build); the clone's origin URL is rewritten to `home`."""
    t = _template()
    for name in ("o.git", "wt"):
        shutil.copytree(t / name, home / name, ignore=shutil.ignore_patterns("*.sample"))
    cfg = home / "wt" / ".git" / "config"
    cfg.write_text(cfg.read_text().replace(str(t / "o.git"), str(home / "o.git")))


def real_git(reason):
    """A test that runs on a real git repo (origin + clone) instead of the gitsim: `reason`, one line, is what only real git can
    show. The marked cells are the integration set; every other engine test runs on the sim, and a real git spawned there fails it."""
    def mark(fn):
        fn.real_git = reason
        return fn
    return mark


def no_repo(fn):
    """The test calls code directly and never touches the repo: setUp skips building origin and clone."""
    fn.no_repo = True
    return fn


def pid_gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


class SlotWorld(Case):
    """A slot's world for a test: the process env a run reads, a gitsim world (or a real origin + clone for @real_git) in `self.wt`, the
    check-markers fake. No bd, no engine."""
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(home / "cfg"),
                "APPDATA": str(home / "cfg"),
                "CLAUDE_CODE_SESSION_ID": "sess1234-x",
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
                "BEADS_DIR": str(home / "no-beads"),
                **NO_GC,
            },
        )  # a bd that slips past the store finds nothing to write
        self.env.start()
        self.wt = home / "wt"
        method = getattr(self, self._testMethodName)
        self.sim = None
        if not getattr(method, "real_git", None):
            gitsim.reset()
            self.sim = gitsim.Sim(self)
            stack = contextlib.ExitStack()
            self.addCleanup(stack.close)
            self.sim.install(stack)
            if not getattr(method, "no_repo", False):
                gitsim.new_world(home)
        elif not getattr(method, "no_repo", False):
            copy_origin_and_clone(home)
        procsim.fake(MARKERS, procsim.markers)

    def teardown_method(self):
        close_held()  # tl-64i: the held log handles live in the temp dir that goes now
        self.env.stop()
        self.tmp.cleanup()
        if self.sim:
            self.sim.check()

    def spawn(self, pidfile, term=False):
        """A check that starts a child sleeping 30 s and records its pid, then waits for it (term: after sending its parent, the
        engine, SIGTERM)."""
        kill = "kill -TERM $PPID; " if term else ""
        script = Path(pidfile).with_suffix(".sh")  # a script, not `sh -c`: a check is an argv, and a shell string is refused
        script.write_text(f"sleep 30 &\necho $! > {shlex.quote(str(pidfile))}\n{kill}wait\n")
        return shlex.join(["sh", str(script)])

    def script(self, name, body):
        """A shell script in the test's temp dir, as the one-line text of a command that runs it."""
        path = Path(self.tmp.name, name)
        path.write_text(body)
        return shlex.join(["sh", str(path)])

    def child_of(self, pidfile, limit=30):
        """The pid the check recorded. A caller that waits for a loaded runner to start the check passes a long limit (the wait ends
        the moment the pid is there; the limit is only the give-up)."""
        if until(lambda: pidfile.exists() and pidfile.read_text().strip(), limit):
            return int(pidfile.read_text())
        pytest.fail("the check never started its child")

    def assertDead(self, pid):
        if not until(lambda: pid_gone(pid), 3):
            os.kill(pid, 9)
            pytest.fail(f"pid {pid} outlived the engine's stop")

    def stoppable(self):
        """The engine's own SIGTERM handler (run_main installs it), restored after the test."""
        if os.name == "nt":
            pytest.skip("POSIX signals")

        return halting.halt_on_sigterm()
