"""One liveness rule and one retention (taskloop.contracts.runlife): a run is live, ended or lost from its manifest's recorded state alone,
the dash API and `tl report` read it the same way, the one reconciler marks a run whose heartbeat is stale and whose pid is gone lost, the
run-start sweep removes old logs with their .live/ folders, and the live API pages a long log. A fake clock throughout; the pids are
numbers (one that is nobody's, and this test process's own)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support import homes  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from support.logs import typed  # noqa: E402
from support.narrow import must  # noqa: E402
from support.runs import manifest  # noqa: E402

from taskloop.app.report import card  # noqa: E402
from taskloop.app.run import layout  # noqa: E402
from taskloop.app.slots.lease import Lease  # noqa: E402
from taskloop.contracts import runlife  # noqa: E402
from taskloop.contracts.enums import Outcome  # noqa: E402
from taskloop.contracts.ids import BeadId, RunId  # noqa: E402
from taskloop.contracts.locator import RunLocator, host_name  # noqa: E402
from taskloop.contracts.paths import ConfigDir  # noqa: E402
from taskloop.contracts.run import RunManifest, RunState  # noqa: E402
from taskloop.contracts.runlife import BEAT_EVERY, KEEP_DAYS, STALE_AFTER, Liveness, liveness  # noqa: E402
from taskloop.contracts.trace import RunTrace  # noqa: E402
from taskloop_dash import jsonl  # noqa: E402
from taskloop_dash.api import live as live_api  # noqa: E402

BEAD, STAMP = "t-1", "20261026-100000"
RUN = f"{BEAD}-{STAMP}"
N = STALE_AFTER
NOBODY = 4_194_303  # a pid no process has


def put(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def started(t: float) -> list[dict]:
    return [typed("run_start", t, run_id=RUN, bead=BEAD, worktree="/w"), typed("step_start", t + 1, id="n1", step="write", text="write")]


class Rule(unittest.TestCase):
    def test_each_recorded_state_reads_one_way(self):
        want = {RunState.CREATED: Liveness.LIVE, RunState.RUNNING: Liveness.LIVE, RunState.DONE: Liveness.ENDED,
                RunState.FAILED: Liveness.ENDED, RunState.PARKED: Liveness.ENDED, RunState.STOPPED: Liveness.ENDED,
                RunState.LOST: Liveness.LOST}
        self.assertEqual(set(want), set(RunState))
        for state, life in want.items():
            m = RunManifest(run=RUN, repo="/r", bead=BEAD, started=0.0, state=state)
            self.assertIs(liveness(m), life, state)

    def test_the_limit_leaves_room_for_missed_beats(self):
        self.assertGreaterEqual(N, 2 * BEAT_EVERY)  # a run is silent at most one beat; N/2 is that and a margin


class Beats(unittest.TestCase):
    def test_every_beat_of_the_lease_also_writes_a_beat_record(self):
        class Store:
            def heartbeat(self, bead):
                pass

        seen: list[str] = []
        lease = Lease(mock.Mock(wraps=Store()), BeadId("t-1"), on_beat=lambda: seen.append("beat"))
        lease.beat()
        lease.beat()
        self.assertEqual(seen, ["beat", "beat"])
        self.assertEqual(lease.every, BEAT_EVERY)


class Crash(unittest.TestCase):
    """A kill -9: the manifest says running and its heartbeat ages. Once the heartbeat is stale and the pid gone the reconciler marks the
    run lost, and the dashboard's live view and the report both read that; a live pid, another host or an ended run is never marked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        home = Path(self.tmp.name)
        self.cfg = home / "task-loop"
        self.t0 = 1_800_000_000.0
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home), "APPDATA": str(home)})
        env.start()
        self.addCleanup(env.stop)
        self.bundle = self.record(pid=NOBODY)
        self.log = self.bundle.log
        put(self.log, [*started(self.t0), typed("beat", self.t0 + 5)])
        os.utime(self.log, (self.t0 + 5, self.t0 + 5))
        self.now = self.t0 + 5
        self.dash = make_dash(config=self.cfg, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, **fields: object):
        base = {"state": RunState.RUNNING, "heartbeat": self.t0 + 5, "host": host_name()}
        return manifest(self.cfg, RUN, BEAD, self.t0, repo="/no/repo", **{**base, **fields})

    def dash_says(self) -> str:
        self.dash.env.files.items.clear()
        return self.dash.live.page(BEAD)[1]["state"]

    def report_crashes(self) -> list[str]:
        run = must(RunId.of("01KBN6Z0M4R5E8YQ2T7C9W3XA1"))
        trace = [RunTrace(run=run, bead=BEAD, repo_url="", worktree="", branch="", coordinator_session="",
                          started=0.0, ended=0.0, outcome=Outcome.FAILED, why="", sha="")]  # makes the bead's prefix one the report knows
        at = self.t0  # a run belongs to the window its manifest's start is in
        found = card.crashes("/no/repo", at - 3600, at + 3600, trace, homes.cfg(), now=self.now)
        return [c["run"] for c in found]

    def test_a_fresh_heartbeat_reads_live_in_both(self):
        self.now = self.t0 + 5 + N - 1
        self.assertEqual(self.dash_says(), "live")
        self.assertEqual(self.report_crashes(), [])

    def test_a_killed_run_reads_lost_once_its_heartbeat_is_stale(self):
        for age in (N, 2 * N):
            self.record(pid=NOBODY)  # running again, as the engine left it
            self.now = self.t0 + 5 + age
            self.assertEqual(self.dash_says(), "lost", age)
            self.assertEqual(self.report_crashes(), [RUN], age)
            self.assertIn("is gone", must(RunLocator(ConfigDir(self.cfg)).get(RUN)).manifest.reason)

    def test_a_stale_run_whose_process_lives_or_is_elsewhere_is_not_lost(self):
        self.now = self.t0 + 5 + 9 * N
        self.record(pid=os.getpid())
        self.assertEqual(self.dash_says(), "live")
        self.record(pid=NOBODY, host="another-machine")
        self.assertEqual(self.dash_says(), "live")

    def test_lost_is_set_once(self):
        self.now = self.t0 + 5 + 2 * N
        where = RunLocator(ConfigDir(self.cfg))
        self.assertEqual(runlife.reconcile(ConfigDir(self.cfg), self.now), [RUN])
        again = where.get(RUN)
        self.assertEqual(runlife.reconcile(ConfigDir(self.cfg), self.now + 99), [])
        self.assertEqual(where.get(RUN), again)

    def test_an_ended_run_reads_ended_in_both(self):
        self.record(state=RunState.DONE, pid=NOBODY)
        self.now = self.t0 + 9 + 50 * N
        self.assertEqual(self.dash_says(), "ended")
        self.assertEqual(self.report_crashes(), [])


class Sweep(unittest.TestCase):
    def test_a_log_older_than_retain_goes_with_its_live_folder_and_a_recent_or_live_one_stays(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            cfg = ConfigDir(Path(d) / "task-loop")
            now = 1_800_000_000.0

            def make(run: str, written: float) -> None:
                manifest(cfg, run, run.rsplit("-", 2)[0], written)
                put(cfg.engine_log(run), [typed("beat", written)])
                cfg.engine_log(run).with_suffix(".stderr").write_text("x")
                (cfg.live_dir(run)).mkdir()
                (cfg.live_dir(run) / "01-write.jsonl").write_text("{}\n")
                for p in (cfg.engine_log(run), cfg.engine_log(run).with_suffix(".stderr")):
                    os.utime(p, (written, written))

            make("t-1-20261001-100000", now - KEEP_DAYS * 86400 - 10)  # old
            make("t-2-20261020-100000", now - KEEP_DAYS * 86400 + 3600)  # recent
            make("t-3-20261029-100000", now - 20)  # a live run
            layout.prune_run_logs(cfg, now, KEEP_DAYS * 86400)
            left = sorted(p.name for p in (cfg.root / "engine").iterdir())
            self.assertEqual(left, sorted(f"{r}.{e}" for r in ("t-2-20261020-100000", "t-3-20261029-100000")
                                          for e in ("jsonl", "stderr", "live")))
            self.assertTrue((cfg.live_dir("t-3-20261029-100000") / "01-write.jsonl").exists())


class BeatsAreNoEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "task-loop"
        self.t0 = 1_800_000_000.0
        self.bundle = manifest(self.cfg, RUN, BEAD, self.t0, state=RunState.RUNNING)
        self.log = self.bundle.log

    def test_100_beats_between_two_events_are_no_events(self):
        put(self.log, started(self.t0))
        put(self.log, [typed("beat", self.t0 + 2 + i) for i in range(100)])
        put(self.log, [typed("warn", self.t0 + 200, text="slow")])
        os.utime(self.log, (self.t0 + 200, self.t0 + 200))
        dash = make_dash(config=self.cfg, clock=lambda: self.t0 + 201)
        run = dash.live.live_run(self.bundle)
        run.refresh()
        self.assertEqual([e["k"] for e in live_api.page(run)["events"]], ["run_start", "step_start", "warn"])
        self.assertEqual(dash.live.page(BEAD)[1]["state"], "live")
        self.assertEqual(jsonl.records(str(self.log))[-1].kind, "warn")


if __name__ == "__main__":
    unittest.main()
