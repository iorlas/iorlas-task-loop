"""One liveness rule and one retention (taskloop.contracts.runlife): a run is live, ended or crashed from its typed log alone, the dash
API and `tl report` read it the same way, the run-start sweep removes old logs with their .live/ folders, and the live API pages a long log.
A fake clock throughout: no process runs and none is probed."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401
from support.dashes import make_dash  # noqa: E402
from support.logs import typed  # noqa: E402

from taskloop.app.report import card  # noqa: E402
from taskloop.app.run import layout  # noqa: E402
from taskloop.app.slots.lease import Lease  # noqa: E402
from taskloop.contracts import log as rec  # noqa: E402
from taskloop.contracts.enums import Outcome  # noqa: E402
from taskloop.contracts.paths import ConfigDir  # noqa: E402
from taskloop.contracts.runlife import BEAT_EVERY, CRASHED_AFTER, RETAIN, Liveness, liveness  # noqa: E402
from taskloop.domain.report import matchers  # noqa: E402

BEAD, STAMP = "t-1", "20261026-100000"
RUN = f"{BEAD}-{STAMP}"
N = CRASHED_AFTER


def put(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def started(t: float) -> list[dict]:
    return [typed("run_start", t, run=RUN, bead=BEAD, worktree="/w"), typed("step_start", t + 1, id="n1", step="write", text="write")]


class Rule(unittest.TestCase):
    def test_the_three_states_and_the_limit(self):
        beat = rec.Beat(t=1000.0)
        self.assertIs(liveness([beat], 1000 + N - 1), Liveness.LIVE)
        self.assertIs(liveness([beat], 1000 + N), Liveness.CRASHED)
        self.assertIs(liveness([beat, rec.Close(t=1010.0, outcome=Outcome.LANDED)], 1000 + 99 * N), Liveness.ENDED)
        self.assertIs(liveness([], 1000.0), Liveness.CRASHED)

    def test_the_limit_leaves_room_for_missed_beats(self):
        self.assertGreaterEqual(N, 2 * BEAT_EVERY)  # a run is silent at most one beat; N/2 is that and a margin


class Beats(unittest.TestCase):
    def test_every_beat_of_the_lease_also_writes_a_beat_record(self):
        class Store:
            def heartbeat(self, bead):
                pass

        seen: list[str] = []
        lease = Lease(mock.Mock(wraps=Store()), "t-1", on_beat=lambda: seen.append("beat"))
        lease.beat()
        lease.beat()
        self.assertEqual(seen, ["beat", "beat"])
        self.assertEqual(lease.every, BEAT_EVERY)


class Crash(unittest.TestCase):
    """A kill -9: the log has no close and its newest record ages. Both readers say crashed within 2N seconds, live before it,
    ended with a close."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        home = Path(self.tmp.name)
        self.cfg = home / "task-loop"
        self.t0 = 1_800_000_000.0
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home), "APPDATA": str(home)})
        env.start()
        self.addCleanup(env.stop)
        self.log = self.cfg / "engine" / f"{RUN}.jsonl"
        put(self.log, [*started(self.t0), typed("beat", self.t0 + 5)])
        os.utime(self.log, (self.t0 + 5, self.t0 + 5))
        self.now = self.t0 + 5
        self.dash = make_dash(config=self.cfg, clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def dash_says(self) -> tuple[str, str, str]:
        self.dash.env.ttl.clear()
        self.dash.env.files.items.clear()
        row = next(t for t in self.dash.tasks.api_tasks()["tasks"] if t["id"] == BEAD)
        got = self.dash.live.api_live(BEAD)
        return row["liveness"], got["liveness"], row["state"]

    def report_crashes(self) -> list[str]:
        trace = [{"bead": BEAD, "run": "other", "worktree": "", "repo": ""}]  # makes the bead's prefix one the report knows
        at = matchers.stem_time(STAMP)  # a run belongs to the window its name's stamp is in
        found = card.crashes("/no/repo", at - 3600, at + 3600, trace, now=self.now)
        return [c["run"] for c in found]

    def test_a_recent_record_reads_live_in_both(self):
        self.now = self.t0 + 5 + N - 1
        self.assertEqual(self.dash_says()[:2], ("live", "live"))
        self.assertEqual(self.dash_says()[2], "running")
        self.assertEqual(self.report_crashes(), [])

    def test_a_run_killed_without_an_end_record_reads_crashed_within_2n_seconds(self):
        for age in (N, 2 * N):
            self.now = self.t0 + 5 + age
            self.assertEqual(self.dash_says()[:2], ("crashed", "crashed"), age)
            self.assertNotEqual(self.dash_says()[2], "running")
            self.assertEqual(self.report_crashes(), [RUN], age)

    def test_a_run_with_an_end_record_reads_ended_in_both(self):
        put(self.log, [typed("close", self.t0 + 9, outcome="landed", why="")])
        os.utime(self.log, (self.t0 + 9, self.t0 + 9))
        self.now = self.t0 + 9 + 50 * N
        self.assertEqual(self.dash_says()[:2], ("ended", "ended"))
        self.assertEqual(self.report_crashes(), [])


class Sweep(unittest.TestCase):
    def test_a_log_older_than_retain_goes_with_its_live_folder_and_a_recent_or_live_one_stays(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            cfg = ConfigDir(Path(d) / "task-loop")
            now = 1_800_000_000.0

            def make(run: str, written: float) -> None:
                put(cfg.engine_log(run), [typed("beat", written)])
                cfg.engine_log(run).with_suffix(".stderr").write_text("x")
                (cfg.live_dir(run)).mkdir()
                (cfg.live_dir(run) / "01-write.jsonl").write_text("{}\n")
                for p in (cfg.engine_log(run), cfg.engine_log(run).with_suffix(".stderr")):
                    os.utime(p, (written, written))

            make("t-1-20261001-100000", now - RETAIN - 10)  # old
            make("t-2-20261020-100000", now - RETAIN + 3600)  # recent
            make("t-3-20261029-100000", now - 20)  # a live run
            layout.prune_run_logs(cfg, now)
            left = sorted(p.name for p in (cfg.root / "engine").iterdir())
            self.assertEqual(left, sorted(f"{r}.{e}" for r in ("t-2-20261020-100000", "t-3-20261029-100000")
                                          for e in ("jsonl", "stderr", "live")))
            self.assertTrue((cfg.live_dir("t-3-20261029-100000") / "01-write.jsonl").exists())


class LongLog(unittest.TestCase):
    def test_2500_events_answer_2000_and_a_before_cursor_that_fetches_the_rest(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            cfg = Path(d) / "task-loop"
            t0 = 1_800_000_000.0
            log = cfg / "engine" / f"{RUN}.jsonl"
            put(log, [typed("note", t0 + i, text=f"line {i}") for i in range(2500)])
            os.utime(log, (t0 + 2500, t0 + 2500))
            dash = make_dash(config=cfg, clock=lambda: t0 + 2501)
            first = dash.live.api_live(BEAD, limit=5000)
            self.assertEqual(len(first["events"]), 2000)
            self.assertTrue(first["before"])
            self.assertEqual(first["events"][-1]["text"], "line 2499")
            rest = dash.live.api_live(BEAD, before=first["before"], limit=5000)
            self.assertEqual(len(rest["events"]), 500)
            self.assertIsNone(rest["before"])
            seqs = {e["seq"] for e in first["events"] + rest["events"]}
            self.assertEqual(len(seqs), 2500)


if __name__ == "__main__":
    unittest.main()
