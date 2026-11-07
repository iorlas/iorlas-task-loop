"""Standalone runs stay visible without beads, and dashboard polls never write their manifests."""
import sys
from pathlib import Path

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.factory_index import ingest
from support.fakes import FakeBeadStore

from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from tlkernel.ids import loop_key
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir
from tlkernel.run import RunState
from tlkernel.runlife import RETAIN
from tlkernel.runrows import RunRows
from tlkernel.slottable import SlotSource
from tltestkit.narrow import must
from tltestkit.repos import write_repos
from tltestkit.runs import manifest


class RunHeaders(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo = root / "lifesim"
        self.repo.mkdir()
        self.cfg = ConfigDir(root / "cfg")
        self.cfg.root.mkdir()
        write_repos(self.cfg.root / "repos.json", self.repo)
        self.locator = RunLocator(self.cfg)
        self.now = 1800000000.0
        ports = Ports(store=lambda repo: FakeBeadStore())
        self.dash = Dash(Env(config=self.cfg.root, home=root, ports=ports, clock=lambda: self.now))
        self.addCleanup(self.dash.reads.wait)

    def snapshot(self):
        ingest(self.cfg, self.now)
        return self.dash.reads.snapshot()

    def create(self, mode="stage:gate", started=None):
        return self.locator.create(str(self.repo), "", self.now if started is None else started,
                                   mode=mode, owner="mac-owner", session="mac-session")

    def test_manifest_only_run_is_visible_on_an_empty_board_with_identity_and_terminal_state(self):
        bundle = self.create()
        self.locator.beat(bundle.run, self.now)
        before = RunRows(self.cfg).snapshot(bundle.run)
        snap = self.snapshot()
        assert snap.beads == []
        assert not bundle.log.exists()
        head, = snap.runs
        assert (
            (head.run, head.project, head.mode, head.owner, head.session, head.state)
            == (bundle.run, loop_key(self.repo), "stage:gate", "mac-owner", "mac-session", RunState.RUNNING)
        )
        assert RunRows(self.cfg).snapshot(bundle.run) == before
        self.locator.end(bundle.run, self.now + 1, RunState.FAILED, "exit 1")
        ended = RunRows(self.cfg).snapshot(bundle.run)
        self.now += 4
        self.snapshot()
        self.dash.reads.wait()
        terminal = self.snapshot()
        assert (terminal.runs[0].state, terminal.runs[0].reason) == (RunState.FAILED, "exit 1")
        assert terminal.version != snap.version
        assert RunRows(self.cfg).snapshot(bundle.run) == ended

    def test_retention_keeps_old_live_runs_and_recent_done_runs(self):
        live = self.create("stage:check", self.now - RETAIN - 10)
        old = self.create(started=self.now - RETAIN - 20)
        self.locator.end(old.run, self.now - RETAIN - 1, RunState.DONE)
        done = self.create()
        self.locator.end(done.run, self.now, RunState.DONE)
        headers = self.snapshot().runs
        assert [h.run for h in headers] == [done.run, live.run]

    def test_snapshot_caps_run_headers_at_ten_newest_first(self):
        # Deliberately create manifests out of start order; locator order is no guarantee.
        created = [self.create(started=self.now - i * 60) for i in (4, 0, 8, 2, 11, 1, 10, 3, 9, 5, 7, 6)]
        headers = self.snapshot().runs
        assert len(headers) == 10
        assert [h.started for h in headers] == [self.now - i * 60 for i in range(10)]
        assert headers[0].run == created[1].run

    def test_engine_layout_manifest_supplies_run_header_identity(self):
        layout = manifest(self.cfg, "t-1-run", "t-1", self.now, repo=str(self.repo),
                          mode="stage:gate", owner="mac-owner", session="mac-session")
        head, = self.snapshot().runs
        assert (head.run, head.mode, head.owner, head.session) == (layout.run, "stage:gate", "mac-owner", "mac-session")

    def test_active_adhoc_work_and_four_configured_lanes_survive_without_slot_beads(self):
        self.dash.env.ports.slot_source = lambda repo: SlotSource(host="h", count=4)
        live = self.create("stage:check")
        done = self.create("stage:gate")
        self.locator.end(done.run, self.now, RunState.DONE)
        self.locator.worktree(live.run, "/repo/slots/s2")
        snap = self.snapshot()
        assert [(r.run, r.branch, r.owner) for r in snap.adhoc] == [(live.run, "s2", "mac-owner")]
        assert [(s.name, s.state) for s in snap.slots] == [(f"s{i}", "free") for i in range(1, 5)]
        stored = must(self.locator.get(live.run)).manifest
        RunRows(self.cfg).put(stored.replace(branch="feature/check"))
        self.now += 4
        self.snapshot()
        self.dash.reads.wait()
        assert self.snapshot().adhoc[0].branch == "feature/check"
        RunRows(self.cfg).put(stored.replace(sha="0123456789abcdef"))
        self.now += 4
        self.snapshot()
        self.dash.reads.wait()
        assert self.snapshot().adhoc[0].branch == "01234567"
