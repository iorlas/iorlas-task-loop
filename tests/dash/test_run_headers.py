"""Standalone runs stay visible without beads, and dashboard polls never write their manifests."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakes import FakeBeadStore
from support.repos import write_repos

from taskloop.app.run.layout import RunLayout
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import RETAIN
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports

STATIC = Path(__file__).resolve().parents[2] / "src" / "taskloop_dash" / "static" / "js"


class RunHeaders(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo = root / "lifesim"
        self.repo.mkdir()
        self.cfg = ConfigDir(root / "cfg")
        self.cfg.root.mkdir()
        write_repos(self.cfg.root / "repos.json", self.repo)
        self.locator = RunLocator(self.cfg)
        self.now = 1800000000.0
        ports = Ports(store=lambda repo: FakeBeadStore(), slot_beads=lambda repo: [])
        self.dash = Dash(Env(config=self.cfg.root, home=root, ports=ports, clock=lambda: self.now))

    def create(self, mode="stage:gate", started=None):
        return self.locator.create(str(self.repo), "", self.now if started is None else started,
                                   mode=mode, owner="mac-owner", session="mac-session")

    def test_manifest_only_run_is_visible_on_an_empty_board_with_identity_and_terminal_state(self):
        bundle = self.create()
        self.locator.beat(bundle.run, self.now)
        before = self.cfg.run_manifest(bundle.run).read_bytes()
        snap = self.dash.reads.snapshot()
        self.assertEqual(snap.beads, [])
        self.assertFalse(bundle.log.exists())
        head, = snap.runs
        self.assertEqual((head.run, head.project, head.mode, head.owner, head.session, head.state),
                         (bundle.run, "lifesim", "stage:gate", "mac-owner", "mac-session", RunState.RUNNING))
        self.assertEqual(self.cfg.run_manifest(bundle.run).read_bytes(), before)
        self.locator.end(bundle.run, self.now + 1, RunState.FAILED, "exit 1")
        ended = self.cfg.run_manifest(bundle.run).read_bytes()
        self.now += 2
        terminal = self.dash.reads.snapshot()
        self.assertEqual((terminal.runs[0].state, terminal.runs[0].reason), (RunState.FAILED, "exit 1"))
        self.assertNotEqual(terminal.version, snap.version)
        self.assertEqual(self.cfg.run_manifest(bundle.run).read_bytes(), ended)

    def test_retention_keeps_old_live_runs_and_recent_done_runs(self):
        live = self.create("stage:check", self.now - RETAIN - 10)
        old = self.create(started=self.now - RETAIN - 20)
        self.locator.end(old.run, self.now - RETAIN - 1, RunState.DONE)
        done = self.create()
        self.locator.end(done.run, self.now, RunState.DONE)
        headers = self.dash.reads.snapshot().runs
        self.assertEqual([h.run for h in headers], [done.run, live.run])

    def test_both_layouts_and_the_empty_board_render_mode_owner_and_session(self):
        page = (STATIC / "app.js").read_text()
        self.assertEqual(page.count("<${RunHeaders} snap=${snap} />"), 2)
        header = (STATIC / "views" / "runs.js").read_text()
        for field in ("mode", "owner", "session", "state"):
            self.assertIn("${r." + field, header)

    def test_engine_layout_manifest_supplies_run_header_identity(self):
        layout = RunLayout.open("t-1", self.repo, None, self.cfg, str(self.repo), self.now,
                                mode="stage:gate", owner="mac-owner", session="mac-session")
        head, = self.dash.reads.snapshot().runs
        self.assertEqual((head.run, head.mode, head.owner, head.session),
                         (layout.run, "stage:gate", "mac-owner", "mac-session"))
