"""One liveness rule and one retention (tlkernel.runlife): a run is live, ended or lost from its manifest's recorded state alone,
the dash API and `tl report` read it the same way, the one reconciler marks a run whose heartbeat is stale and whose pid is gone lost, the
run-start sweep removes old logs with their .live/ folders, and the live API pages a long log. A fake clock throughout; the pids are
numbers (one that is nobody's, and this test process's own)."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support import homes  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from support.factory_index import ingest  # noqa: E402

from taskloop.app.report import card  # noqa: E402
from tlslots.lease import Lease  # noqa: E402
from taskloop_dash import jsonl  # noqa: E402
from taskloop_dash.api import live as live_api  # noqa: E402
from tlkernel import runlayout as layout  # noqa: E402
from tlkernel import runlife  # noqa: E402
from tlkernel.enums import Outcome  # noqa: E402
from tlkernel.ids import BeadId, RunId, loop_key  # noqa: E402
from tlkernel.locator import RunLocator, host_name  # noqa: E402
from tlkernel.paths import ConfigDir  # noqa: E402
from tlkernel.run import RunManifest, RunState  # noqa: E402
from tlkernel.runlife import BEAT_EVERY, KEEP_DAYS, STALE_AFTER, Liveness, liveness  # noqa: E402
from tlkernel.trace import RunTrace  # noqa: E402
from tltestkit.logs import typed  # noqa: E402
from tltestkit.narrow import must  # noqa: E402
from tltestkit.runs import manifest  # noqa: E402

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


class Rule(Case):
    def test_each_recorded_state_reads_one_way(self):
        want = {RunState.CREATED: Liveness.LIVE, RunState.RUNNING: Liveness.LIVE, RunState.DONE: Liveness.ENDED,
                RunState.FAILED: Liveness.ENDED, RunState.PARKED: Liveness.ENDED, RunState.STOPPED: Liveness.ENDED,
                RunState.LOST: Liveness.LOST}
        assert set(want) == set(RunState)
        for state, life in want.items():
            m = RunManifest(run=RUN, repo="/r", bead=BEAD, started=0.0, state=state)
            assert liveness(m) is life, state

    def test_the_limit_leaves_room_for_missed_beats(self):
        assert N >= 2 * BEAT_EVERY  # a run is silent at most one beat; N/2 is that and a margin


class Decision(Case):
    """is_lost is the one decision: the writer applies it and the read-only dashboard displays it, so they cannot differ."""

    def m(self, **kw):
        base = RunManifest(run=RUN, repo="/r", bead=BEAD, started=0.0, state=RunState.RUNNING, heartbeat=1000.0, host="h", pid=7)
        return base.replace(**kw)

    def test_only_a_stale_live_run_of_this_host_with_a_dead_pid_is_lost(self):
        dead, alive = (lambda p, start="": False), (lambda p, start="": True)
        late = 1000.0 + N
        assert runlife.is_lost(self.m(), "h", late, dead)
        assert not runlife.is_lost(self.m(), "h", late - 1, dead)  # fresh heartbeat
        assert not runlife.is_lost(self.m(), "h", late, alive)  # its process lives
        assert not runlife.is_lost(self.m(), "other", late, dead)  # another machine's pid says nothing
        assert not runlife.is_lost(self.m(state=RunState.DONE), "h", late, dead)  # terminal stays
        assert runlife.is_lost(self.m(pid=0), "h", late, alive)  # no pid recorded

    def test_a_gone_pid_is_suspect_after_two_missed_beats_not_running_until_the_reconciler_marks_it(self):
        """A killed engine is not shown running for the five minutes before `lost`: its heartbeat is two beats old and its process
        (pid and start token) is gone, so a reader shows it SUSPECT; the recorded state and the reconciler are untouched."""
        dead, alive = (lambda p, start="": False), (lambda p, start="": True)
        t = 1000.0 + runlife.SUSPECT_AFTER
        assert runlife.suspect(self.m(), "h", t, dead)
        assert not runlife.suspect(self.m(), "h", t - 1, dead)  # a beat or two late is normal
        assert not runlife.suspect(self.m(), "h", t, alive)
        assert not runlife.suspect(self.m(), "other", t, dead)
        assert not runlife.suspect(self.m(state=RunState.DONE), "h", t, dead)
        assert runlife.SUSPECT_AFTER < N
        assert not runlife.is_lost(self.m(), "h", t, dead)  # lost is still written only after STALE_AFTER

    def test_a_pid_another_process_took_over_is_not_the_run(self):
        """After a reboot the run's pid may belong to an unrelated process: only the recorded start token says it is still the run."""
        same_start = lambda p, start="": start == "t1"  # noqa: E731
        late = 1000.0 + N
        assert not runlife.is_lost(self.m(pid_start="t1"), "h", late, same_start)
        assert runlife.is_lost(self.m(pid_start="t0"), "h", late, same_start)

    def test_what_the_dashboard_shows_is_what_reconcile_writes(self):
        with TemporaryDirectory() as d:
            cfg = ConfigDir(Path(d))
            now = 1_800_000_000.0
            for run, pid in (("r-dead", NOBODY), ("r-live", os.getpid())):
                manifest(cfg, run, BEAD, now - 9999, state=RunState.RUNNING, heartbeat=now - 9999, host=host_name(), pid=pid)
            before = {b.run: runlife.shown(b.manifest, now) for b in RunLocator(cfg).runs()}
            assert before == {"r-dead": Liveness.LOST, "r-live": Liveness.LIVE}
            soon = now - 9999 + runlife.SUSPECT_AFTER
            assert runlife.shown(RunLocator(cfg).get("r-dead").manifest, soon) is Liveness.SUSPECT  # type: ignore[union-attr]
            assert runlife.shown(RunLocator(cfg).get("r-live").manifest, soon) is Liveness.LIVE  # type: ignore[union-attr]
            assert RunLocator(cfg).get("r-dead").manifest.state == RunState.RUNNING  # showing wrote nothing  # type: ignore[union-attr]
            assert runlife.reconcile(cfg, now) == ["r-dead"]
            after = {b.run: liveness(b.manifest) for b in RunLocator(cfg).runs()}
            assert after == before


class Beats(Case):
    def test_every_beat_of_the_lease_also_writes_a_beat_record(self):
        class Store:
            def heartbeat(self, bead):
                pass

        seen: list[str] = []
        lease = Lease(mock.Mock(wraps=Store()), BeadId("t-1"), on_beat=lambda: seen.append("beat"))
        lease.beat()
        lease.beat()
        assert seen == ["beat", "beat"]
        assert lease.every == BEAT_EVERY


class Crash(Case):
    """A kill -9: the manifest says running and its heartbeat ages. Once the heartbeat is stale and the pid gone the reconciler marks the
    run lost, and the dashboard's live view and the report both read that; a live pid, another host or an ended run is never marked."""

    def setup_method(self):
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
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

    def teardown_method(self):
        self.tmp.cleanup()

    def record(self, **fields: object):
        base = {"state": RunState.RUNNING, "heartbeat": self.t0 + 5, "host": host_name()}
        return manifest(self.cfg, RUN, BEAD, self.t0, repo="/no/repo", **{**base, **fields})

    def dash_says(self) -> str:
        runlife.reconcile(ConfigDir(self.cfg), self.now)
        ingest(self.cfg, self.now)
        self.dash.env.files.items.clear()
        return self.dash.live.page(loop_key(self.bundle.repo), BEAD)[1]["state"]

    def report_crashes(self) -> list[str]:
        run = must(RunId.of("01KBN6Z0M4R5E8YQ2T7C9W3XA1"))
        trace = [RunTrace(run=run, bead=BEAD, repo_url="", worktree="", branch="", coordinator_session="",
                          started=0.0, ended=0.0, outcome=Outcome.FAILED, why="", sha="")]  # makes the bead's prefix one the report knows
        at = self.t0  # a run belongs to the window its manifest's start is in
        found = card.crashes("/no/repo", at - 3600, at + 3600, trace, homes.cfg(), now=self.now)
        return [c["run"] for c in found]

    def test_a_fresh_heartbeat_reads_live_in_both(self):
        self.now = self.t0 + 5 + runlife.SUSPECT_AFTER - 1
        assert self.dash_says() == "live"
        assert self.report_crashes() == []

    def test_a_killed_run_is_not_shown_live_before_the_reconciler_would_write_lost(self):
        self.now = self.t0 + 5 + runlife.SUSPECT_AFTER
        assert self.dash_says() == "lost"
        assert self.report_crashes() == []  # nothing written: the report counts a crash only once `lost` is recorded

    def test_a_killed_run_reads_lost_once_its_heartbeat_is_stale(self):
        for age in (N, 2 * N):
            self.record(pid=NOBODY)  # running again, as the engine left it
            self.now = self.t0 + 5 + age
            assert self.dash_says() == "lost", age
            assert self.report_crashes() == [RUN], age
            assert "is gone" in must(RunLocator(ConfigDir(self.cfg)).get(RUN)).manifest.reason

    def test_a_stale_run_whose_process_lives_or_is_elsewhere_is_not_lost(self):
        self.now = self.t0 + 5 + 9 * N
        self.record(pid=os.getpid())
        assert self.dash_says() == "live"
        self.record(pid=NOBODY, host="another-machine")
        assert self.dash_says() == "live"

    def test_lost_is_set_once(self):
        self.now = self.t0 + 5 + 2 * N
        where = RunLocator(ConfigDir(self.cfg))
        assert runlife.reconcile(ConfigDir(self.cfg), self.now) == [RUN]
        again = where.get(RUN)
        assert runlife.reconcile(ConfigDir(self.cfg), self.now + 99) == []
        assert where.get(RUN) == again

    def test_an_ended_run_reads_ended_in_both(self):
        self.record(state=RunState.DONE, pid=NOBODY)
        self.now = self.t0 + 9 + 50 * N
        assert self.dash_says() == "ended"
        assert self.report_crashes() == []


class Sweep(Case):
    def test_a_log_older_than_retain_goes_with_its_live_folder_and_a_recent_or_live_one_stays(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as d:
            cfg = ConfigDir(Path(d) / "task-loop")
            now = 1_800_000_000.0

            def make(run: str, written: float) -> None:
                manifest(cfg, run, run.rsplit("-", 2)[0], written)
                put(cfg.engine_log(run), [typed("beat", written)])
                cfg.engine_stderr(run).write_text("x")
                (cfg.live_dir(run)).mkdir()
                (cfg.live_dir(run) / "01-write.jsonl").write_text("{}\n")
                for p in (cfg.engine_log(run), cfg.engine_stderr(run)):
                    os.utime(p, (written, written))

            make("t-1-20261001-100000", now - KEEP_DAYS * 86400 - 10)  # old
            make("t-2-20261020-100000", now - KEEP_DAYS * 86400 + 3600)  # recent
            make("t-3-20261029-100000", now - 20)  # a live run
            layout.prune_run_logs(cfg, now, KEEP_DAYS * 86400)
            left = sorted(p.relative_to(cfg.runs_dir()).as_posix() for r in cfg.runs_dir().iterdir() for p in r.iterdir()
                          if p.name in ("engine.jsonl", "stderr.log", "live"))
            assert left == sorted(f"{r}/{e}" for r in ("t-2-20261020-100000", "t-3-20261029-100000")
                                  for e in ("engine.jsonl", "stderr.log", "live"))
            assert (cfg.live_dir("t-3-20261029-100000") / "01-write.jsonl").exists()


class BeatsAreNoEvents(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
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
        ingest(self.cfg, self.t0 + 201)
        run = dash.live.live_run(self.bundle.run)
        run.refresh()
        assert [e["kind"] for e in live_api.page(run)["events"]] == ["run_start", "step_start", "warn"]
        assert dash.live.page(loop_key(self.bundle.repo), BEAD)[1]["state"] == "live"
        assert jsonl.records(str(self.log))[-1].kind == "warn"
