"""The live feed of GET /api/live: the engine log merged with the worker's live files by time; the engine hands delegate the file."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from support.case import Case

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "task-loop"
for sub in ("dash", "", "tests"):
    sys.path.insert(0, str(SKILL / sub) if sub != "tests" else str(ROOT / "tests"))
import support.paths  # noqa: E402, F401
from support import dlcall, fake_route  # noqa: E402
from support.factory_index import ingest  # noqa: E402
from support.logs import typed  # noqa: E402
from support.narrow import must  # noqa: E402
from support.runs import manifest  # noqa: E402

from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.adapters import runner as live_runner  # noqa: E402
from taskloop.app.run import engine  # noqa: E402
from taskloop.contracts.paths import ConfigDir  # noqa: E402
from taskloop_dash.api import live  # noqa: E402

BEAD, STAMP = "tl-live.1", "20261026-100000"
T = 1793000000.0


def put(path, rows, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def make_run(root):
    """An engine log with a command and a write step, and the live file of its write call."""
    eng = os.path.join(root, "task-loop", "engine")
    b = manifest(os.path.join(root, "task-loop"), f"{BEAD}-{STAMP}", BEAD, T)
    log = str(b.log)
    put(log, [typed("run_start", T, run_id=f"{BEAD}-{STAMP}", bead=BEAD, worktree=""),
              typed("cmd_start", T + 1, id="m1", text="git fetch -q origin"),
              typed("cmd_end", T + 3, id="m1", exit=0),
              typed("step_start", T + 4, id="n1", text="write: x", step="write"),
              typed("call_start", T + 5, id="c1", n=1, step="write", node="n1", role="worker")])
    lf = os.path.join(eng, f"{BEAD}-{STAMP}.live", "01-write.jsonl")
    put(
        lf,
        [
            {"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "effort": "high", "role": "worker", "pid": 1},
            {"t": T + 6.5, "k": "msg", "text": "between the start and the command"},
            {"t": T + 7, "k": "cmd_start", "id": "1", "text": "pytest -q", "cwd": "/w"},
        ],
    )
    return b, lf


class Feed(Case):
    def test_a_burst_larger_than_one_page_is_delivered_in_full_across_polls(self):
        with tempfile.TemporaryDirectory() as d:
            _log, lf, run = self.run_of(d)
            self.refresh(run)
            first = live.page(run)
            n = live.MAX_PAGE + 50
            put(lf, [{"t": T + 10 + i / 1000, "k": "msg", "text": f"m{i}"} for i in range(n)])
            self.refresh(run)
            seen, cursor = [], live.decode(first["cursor"])
            for _ in range(5):
                got = live.page(run, cursor)
                seen += [e["text"] for e in got["events"] if e.get("text", "").startswith("m")]
                cursor = live.decode(got["cursor"])
                if not got["events"]:
                    break
            assert seen == [f"m{i}" for i in range(n)]

    def test_a_replaced_worker_file_of_the_same_size_or_larger_starts_over_and_a_deleted_one_leaves_the_feed(self):
        with tempfile.TemporaryDirectory() as d:
            _log, lf, run = self.run_of(d)
            self.refresh(run)
            before = [e.get("text") for e in run.events()]
            assert "between the start and the command" in before
            replacement = lf + ".new"
            put(replacement, [{"t": T + 6.5, "k": "msg", "text": "x" * 400}, {"t": T + 7, "k": "msg", "text": "after replacement"}], "w")
            os.replace(replacement, lf)
            self.refresh(run)
            texts = [e.get("text") for e in run.events()]
            assert "after replacement" in texts
            assert "between the start and the command" not in texts
            os.unlink(lf)
            self.refresh(run)
            assert "after replacement" not in [e.get("text") for e in run.events()]

    def test_a_cursor_of_another_run_is_a_reset_not_a_silent_skip(self):
        with tempfile.TemporaryDirectory() as d:
            _log, _lf, run = self.run_of(d)
            self.refresh(run)
            mine = live.page(run)
            assert mine["reset"] is False
            assert live.page(run, live.decode(mine["cursor"]))["reset"] is False
            foreign = must(live.decode(mine["cursor"]))
            foreign["_run"] += 1
            got = live.page(run, foreign)
            assert got["reset"] is True
            assert got["events"]

    def run_of(self, d):
        b, lf = make_run(d)
        return str(b.log), lf, live.LiveRun(ConfigDir(Path(d) / 'task-loop'), b.run)

    def refresh(self, run):
        ingest(run.cfg, time.time())
        run.refresh()

    def test_merge_by_time_seq_keys_and_the_cursor(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            self.refresh(run)
            a = live.page(run)
            ts = [e["t"] for e in a["events"]]
            assert ts == sorted(ts)
            assert [e["seq"].split(":")[0] for e in a["events"]][:3] == ["engine", "engine", "engine"]
            assert len({e["seq"] for e in a["events"]}) == len(a["events"])
            pairs = {(e["src"], e["k"], e.get("id")) for e in a["events"]}
            assert ("engine", "cmd_end", "m1") in pairs
            assert ("01-write", "cmd_start", "1") in pairs
            assert live.page(run, live.decode(a["cursor"]))["events"] == []  # nothing new: nothing
            put(lf, [{"t": T + 9, "k": "cmd_end", "id": "1", "exit": 1, "out": "boom", "secs": 2.0}])
            with open(lf, "a") as f:
                f.write(f'{{"t": {T + 10}, "k": "msg", "te')  # a half-written line waits
            self.refresh(run)
            b = live.page(run, live.decode(a["cursor"]))
            assert [(e["k"], e["id"]) for e in b["events"]] == [("cmd_end", "1")]
            with open(lf, "a") as f:
                f.write('xt": "hi"}\n')
            put(log, [typed("warn", T + 11, text="slow")])
            self.refresh(run)
            c = live.page(run, live.decode(b["cursor"]))
            assert [(x["k"], x["t"]) for x in c["events"]] == [("msg", T + 10), ("warn", T + 11)]
            assert live.decode("garbage!") is None

    def test_every_engine_kind_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            log, _lf, run = self.run_of(d)
            put(
                log,
                [
                    typed("wait_start", T + 12, id="w1", what="lane", holder="DEEPSEEK_FREE"),
                    typed("wait_end", T + 13, id="w1", wait_seconds=60),
                    typed("vendor_error", T + 14, node="write", reason="hung"),
                    typed("kill", T + 15, what="call", why="silent"),
                    typed("lock", T + 16, what="land_lock", holder="tl-2"),
                    typed("unlock", T + 17, what="land_lock", secs=1.0),
                ],
            )
            self.refresh(run)
            got = {e["k"]: e for e in live.page(run)["events"]}
            for k in ("wait_start", "wait_end", "vendor_error", "kill", "lock", "unlock"):
                assert k in got
            assert (got["wait_end"]["wait_seconds"], got["vendor_error"]["reason"]) == (60, "hung")

    def test_engine_cursor_survives_a_fresh_reader(self):
        with tempfile.TemporaryDirectory() as d:
            log, _lf, run = self.run_of(d)
            run.refresh()
            cursor = live.page(run)["cursor"]
            put(log, [typed("warn", T + 20, text="appended")])
            fresh = live.LiveRun(run.cfg, run.run)
            fresh.refresh()
            assert [e["k"] for e in live.page(fresh, live.decode(cursor))["events"]] == ["warn"]

    def test_a_run_without_worker_files(self):
        with tempfile.TemporaryDirectory() as d:
            _log, lf, run = self.run_of(d)
            os.remove(lf)
            self.refresh(run)
            assert {e["src"] for e in run.events()} == {"engine"}

    def test_long_poll_returns_when_a_file_grows_and_waits_when_none_does(self):
        with tempfile.TemporaryDirectory() as d:
            _log, lf, run = self.run_of(d)
            assert live.poll(run, None)
            cur = live.page(run)["cursor"]
            now = [0.0]
            naps = []

            def nap(secs):
                naps.append(secs)
                now[0] += secs

            assert live.poll(run, live.decode(cur), wait=0.5, sleep=nap, clock=lambda: now[0])["events"] == []
            assert sum(naps) >= 0.5  # nothing grew: it held the whole wait

            def grow(secs):
                nap(secs)
                put(lf, [{"t": T + 30, "k": "tool_start", "id": "9", "text": "edit"}])

            now[0], naps[:] = 0.0, []
            got = live.poll(run, live.decode(cur), wait=2, sleep=grow, clock=lambda: now[0])
            assert len(naps) == 1  # a file grew: it returned at once
            assert [e["k"] for e in got["events"]] == ["tool_start"]


class CallSite(Case):
    def test_file_name(self):
        p = live_runner.live_path("/e/r1.live", 3, "write")
        assert p == "/e/r1.live/03-write.jsonl"
        assert live_runner.live_path("/e/x.live", 12, "re view/2").endswith(".live/12-re-view-2.jsonl")

    def test_the_call_sets_the_env(self):

        seen = []

        def runner(cmd, **kw):
            seen.append(kw.get("env"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        res = dl.Resolved(Path("/fake"), "/fake/route.py", fake_route.CONTRACT, "explicit")
        dlcall.call(res, "worker", "p", {}, ".", runner, live_file="/x/y.live/01-write.jsonl")
        assert must(seen[0])["DELEGATE_LIVE_FILE"] == "/x/y.live/01-write.jsonl"
        dlcall.call(res, "worker", "p", {}, ".", runner, env={})
        assert "DELEGATE_LIVE_FILE" not in must(seen[1])

    def test_engine_numbers_its_calls(self):
        with tempfile.TemporaryDirectory() as d:
            e = object.__new__(engine.Engine)
            e.live_dir, e.live_n = Path(d) / (f"{BEAD}-{STAMP}.live"), 0
            p1, p2 = e.live("plan"), e.live("write")
            assert p1.endswith(".live/01-plan.jsonl") and p2.endswith(".live/02-write.jsonl")
            assert os.path.isdir(os.path.dirname(p1))
            src = Path(engine.__file__).with_name("worker_call.py").read_text(encoding="utf-8")
            assert src.count("e.live(") == 1  # the one delegate call site passes it
