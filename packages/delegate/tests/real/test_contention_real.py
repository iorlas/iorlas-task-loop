"""Real processes sharing the router's files; only readiness and usage are synthetic."""

import concurrent.futures
import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import hermetic  # noqa: F401
from stream_proc import stop_tree

from delegate.contracts.state import Dwell
from delegate.contracts.stores import StateStore
from tltestkit.case import Case
from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory

T = 1_800_000_000
ACCOUNTS = ("OPENAI_SUBSCRIPTION", "GROK_SUBSCRIPTION", "DEEPSEEK_FREE", "ZAI_CODING_SUBSCRIPTION")
N = len(ACCOUNTS)
ROUNDS = 20

# A fresh interpreter calls the real launcher/CLI and the real file writers. Pipes
# rendezvous before contention, and (for next) after routing but before its write.
CHILD = r"""
import contextlib, datetime, io, json, runpy, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "packages" / "delegate" / "src"))
from delegate.app import env, onboard, usage

mode, account, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
main = runpy.run_path("packages/delegate/src/delegate/entry.py")["main"]
def call(args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert main(args) == 0
    return out.getvalue()
def gate():
    print("ready", file=sys.__stdout__, flush=True)
    assert sys.stdin.readline() == "go\n"
if mode == "route":
    load = env.load_routing
    def routing():
        cfg = load()
        cfg["accounts"]["CLAUDE_SECONDARY"] = dict(cfg["accounts"]["CLAUDE_SUBSCRIPTION"])
        return cfg
    env.load_routing = routing
    onboard.configured_accounts = lambda cfg: dict.fromkeys(cfg["accounts"], True)
    usage.READERS.update({k: lambda *a: None for k in usage.READERS})
    update = env.update_state
    waiting = True
    def paused(fn):
        global waiting
        if fn.__name__ == "mark" and waiting:
            waiting = False
            gate()
        return update(fn)
    env.update_state = paused
gate()
for i in range(rounds):
    if mode == "route":
        until = datetime.datetime.fromtimestamp(env.now() + 3600, datetime.timezone.utc).isoformat()
        call(["report", "--account", account, "--event", "out", "--until", until])
        d = json.loads(call(["next", "worker"]))
        assert (d["action"], d["account"]) == ("run", "CLAUDE_SUBSCRIPTION"), d
    else:
        call(["config", "set", "profile.accounts." + account, "enabled"])
        def increment(cur):
            n = cur["min_dwell_minutes"]
            time.sleep(0.003)  # widen the read/write window while holding the existing lock
            cur["min_dwell_minutes"] = n + 1
        env.update_config(increment)
"""


# Each case starts several python children that import the whole delegate package (seconds apiece on a busy host), over the 15 s default.
LIMIT_S = 60


class Contention(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.cfg = self.base / "cfg"
        self.cfg.mkdir()
        self.config = self.cfg / "config.json"
        self.config.write_text(json.dumps({"min_dwell_minutes": 30, "profile": {"accounts": dict.fromkeys(ACCOUNTS, "declined")}}))
        self.children: list[subprocess.Popen[bytes]] = []
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=N)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for p in self.children:
            if p.poll() is None:
                stop_tree(p, grace=0.1)
            p.wait(timeout=10)
            for pipe in (p.stdin, p.stdout, p.stderr):
                if pipe is not None:
                    pipe.close()

    def start(self, mode):
        child_env = dict(
            os.environ,
            HOME=str(self.base),
            USERPROFILE=str(self.base),
            PATH="",
            XDG_CONFIG_HOME=str(self.base / "xdg"),
            XDG_DATA_HOME=str(self.base / "data"),
            CODEX_HOME=str(self.base / "codex"),
            DELEGATE_CONFIG_DIR=str(self.cfg),
            DELEGATE_NOW=str(T),
        )
        for account in ACCOUNTS:
            p = subprocess.Popen(
                [sys.executable, "-c", CHILD, mode, account, str(ROUNDS)],
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self.children.append(p)
        self.ready()

    def ready(self):
        reads = []
        for p in self.children:
            assert p.stdout is not None
            reads.append(self.pool.submit(p.stdout.readline))
        for p, read in zip(self.children, reads, strict=True):
            line = read.result(timeout=20)
            assert p.stderr is not None
            assert line == b"ready\n", line if line else p.stderr.read().decode()

    def release(self):
        for p in self.children:
            assert p.stdin is not None
            p.stdin.write(b"go\n")
            p.stdin.flush()

    def finish(self):
        for p in self.children:
            _out, err = p.communicate(timeout=30)
            assert p.returncode == 0, err
            assert err == b""

    @contextlib.contextmanager
    def observing(self, paths):
        """Read without a lock, as dashboards do; every observed replacement must be whole JSON."""
        done = threading.Event()
        errors, seen = [], set()

        def observe():
            while not done.is_set():
                for path in paths():
                    try:
                        json.loads(path.read_text())
                        seen.add(path)
                    except FileNotFoundError:
                        pass
                    except Exception as e:
                        errors.append((str(path), str(e)))
                done.wait(0.001)

        reader = threading.Thread(target=observe)
        reader.start()
        try:
            yield seen
        finally:
            done.set()
            reader.join(timeout=5)
        assert not reader.is_alive()
        assert errors == []

    @real_proc("delegate: a worker, git or CLI process")
    def test_parallel_report_and_next_preserve_out_marks_and_fresh_dwell(self):
        state = self.cfg / "state.json"
        with self.observing(lambda: [state]) as seen:
            self.start("route")
            self.release()
            self.ready()  # all four routed using a snapshot without prev.claude
            store = StateStore(state)
            store.update(lambda s: s.prev.__setitem__("claude", Dwell(account="CLAUDE_SUBSCRIPTION", since=T - 1)))
            self.release()
            self.finish()
        assert state in seen
        doc = json.loads(state.read_text())
        assert set(doc["out"]) == set(ACCOUNTS)
        for mark in doc["out"].values():
            assert (mark["until"], mark["at"], mark["source"]) == (T + 3600, T, "manual")
        assert doc["prev"] == {"claude": {"account": "CLAUDE_SUBSCRIPTION", "since": T - 1}}

    @real_proc("delegate: a worker, git or CLI process")
    def test_parallel_config_cli_and_update_config_lose_no_updates(self):
        with self.observing(lambda: [self.config]) as seen:
            self.start("config")
            self.release()
            self.finish()
        assert self.config in seen
        doc = json.loads(self.config.read_text())
        assert doc["min_dwell_minutes"] == (30 + N * ROUNDS)
        assert doc["profile"]["accounts"] == dict.fromkeys(ACCOUNTS, "enabled")
