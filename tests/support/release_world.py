"""A release's outside world inside the test's process: bare git repos in a temp dir, and `claude`, `just`, `bd` and the suite faked.

`flow.main` runs in the test's process. Git stays real (the rebases, the pushes and the push race are what a release is about); what is
faked is what lives outside the repo: `claude plugin update` lays the new version's cache dir out as the real CLI does (or fails like
0.23.0: a fetch-pack error, exit 0, nothing installed), `just check` answers `just_exit`, bd is a FakeBeadStore, and the suite is
`World.suite`: it records the tree it was run on, calls the test's `on_suite`, and is red when the tree holds tests/RED (its text is the
suite output)."""
import io
import json
import os
import subprocess
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from support.fakes import FakeBeadStore
from taskloop.adapters import beadtools
from taskloop.adapters.git import RealGit
from taskloop.adapters.ident import claude_dir
from taskloop.app.release import flow, shell, suite
from taskloop.app.release.shell import say
from taskloop.contracts.ports import Ran, Spawner

PLUGIN = ".claude-plugin/plugin.json"
MARKET = ".claude-plugin/marketplace.json"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
FETCH_PACK = "fatal: fetch-pack: invalid index-pack output\n"


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Out:
    """sys.stdout / sys.stderr that keep apart what each thread prints (two releases run at once in the queue test)."""

    def __init__(self):
        self.local = threading.local()
        self.bufs: dict[str, io.StringIO] = {}  # by release, readable from another thread while it runs

    def start(self, key: str) -> None:
        self.local.buf = self.bufs[key] = io.StringIO()

    def text(self) -> str:
        return self.local.buf.getvalue()

    def write(self, text: str) -> int:
        buf = getattr(self.local, "buf", None)
        return buf.write(text) if buf is not None else len(text)

    def flush(self) -> None:
        pass


class Result(SimpleNamespace):
    """returncode, stdout, stderr of one release."""


class World:
    def __init__(self, home: Path, repo: Path, market: Path):
        self.home, self.repo, self.market = home, repo, market
        self.claude_log: list[list[str]] = []
        self.claude_fail = ""  # "always" | "once" | ""
        self.failed_once = False
        self.just_exit = 0
        self.just_log: list[list[str]] = []
        self.store = FakeBeadStore()
        self.before_push = None  # called once, just before the release clone's push of main
        self.on_suite = None  # called with the tree under test inside every suite run
        self.trees: list[dict[str, bytes]] = []  # the tracked files of every tree the suite ran on
        self.stdout, self.stderr = Out(), Out()

    def spawn(self, argv, *, cwd=None, **_: Any) -> Ran:
        """Spawner.run for the release's calls: the real or the faked process, as the port's record. `just` / `mise` are the gate."""
        if argv[0] in ("just", "mise"):
            self.just_log.append(list(argv))
            return Ran(exit=self.just_exit, out="ruff: E501 somewhere\n")
        r = self.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return Ran(exit=r.returncode, out=r.stdout or "", err=r.stderr or "")

    def claude(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        self.claude_log.append(cmd[1:])
        if cmd[1:3] == ["plugin", "update"]:
            if self.claude_fail == "always" or (self.claude_fail == "once" and not self.failed_once):
                self.failed_once = True
                return subprocess.CompletedProcess(cmd, 0, FETCH_PACK, "")
            plugins = json.loads((self.market / MARKET).read_text())["plugins"]
            v = next(p["version"] for p in plugins if p["name"] == "iorlas-task-loop")
            d = claude_dir() / "plugins/cache/iorlas-marketplace/iorlas-task-loop" / v / ".claude-plugin"
            d.mkdir(parents=True, exist_ok=True)
            (d / "plugin.json").write_text("{}")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def run(self, cmd, **kw: Any):
        """subprocess.run for the release's calls: claude is faked, a push of main from the release clone first calls `before_push`."""
        if cmd[0] == "claude":
            return self.claude(list(cmd))
        if cmd[:2] == ["git", "push"] and "HEAD:main" in cmd and self.before_push and Path(kw["cwd"]) != self.market:
            hook, self.before_push = self.before_push, None
            hook()
        kw.pop("check", None)  # the release asks for check=False, always
        return subprocess.run(cmd, check=False, **kw)

    @property
    def spawner(self) -> Spawner:
        """What the release is handed at its edge: the world's processes (git real, claude and the gate faked)."""
        return cast(Spawner, SimpleNamespace(run=self.spawn))

    def suite(self, tool_root: Path, repo: Path, sh: shell.Shell) -> None:
        suite.gate(repo, sh)
        say("running the full suite in 1 workers, then the serial group")
        tree = {p: (repo / p).read_bytes() for p in git("ls-files", cwd=repo).splitlines()}
        self.trees.append(tree)
        if self.on_suite:
            self.on_suite(repo)
        if "tests/RED" in tree:
            out = tree["tests/RED"].decode()
            raise suite.red(out, out.splitlines())
        say("suite green")

    def verify(self, tool_root: Path, repo: Path, sh: shell.Shell) -> bool:
        return REAL_VERIFY(tool_root, repo, sh, self.suite)

    def release(self, *args: str) -> Result:
        """flow.main on `args` in this thread; its stdout and stderr, and its exit code."""
        self.stdout.start(args[0])
        self.stderr.start(args[0])
        try:
            code = flow.main([*args, "--repo", str(self.repo), "--marketplace", str(self.market)], Path(__file__).resolve().parents[2],
                             self.spawner, RealGit())
        except SystemExit as e:
            code = e.code
        return Result(returncode=code, stdout=self.stdout.text(), stderr=self.stderr.text())

    @contextmanager
    def active(self, env: dict[str, str]):
        """The faked world for a `with`: the environment, the fake claude / just / bd / suite, and the thread-aware stdout."""
        with ExitStack() as st:
            st.enter_context(mock.patch.dict(os.environ, env))
            for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "TL_RELEASE_REEXEC"):
                os.environ.pop(k, None)
            st.enter_context(mock.patch.object(flow.suite, "verify", self.verify))
            st.enter_context(mock.patch.object(beadtools, "bd_store", lambda cwd=None: self.store))
            st.enter_context(mock.patch("sys.stdout", self.stdout))
            st.enter_context(mock.patch("sys.stderr", self.stderr))
            yield self


REAL_VERIFY = suite.verify  # taken before `active` replaces it: the cache and the command line stay the real ones
