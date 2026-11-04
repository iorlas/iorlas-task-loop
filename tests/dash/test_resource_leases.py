"""The Floor reads resource holder hints through ConfigDir without taking or changing a lock."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from any_lease import Leases
from support.factory_index import ingest
from support.fakes import FakeBeadStore
from support.repos import write_repos

from taskloop.adapters.locks import resource_holders
from taskloop.contracts.ids import loop_key
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports


class ResourceLeases(unittest.TestCase):
    def test_a_held_lease_is_read_only_and_joined_to_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, repo = ConfigDir(root / "cfg"), root / "project"
            repo.mkdir()
            cfg.root.mkdir()
            write_repos(cfg.repos(), repo)
            run = RunLocator(cfg).create(str(repo), "", 1000, mode="stage:check")
            table = Leases(cfg.leases())
            unit = table.acquire("unity", 2, label="owner:unity-check")  # this process holds one of two units; the other is free
            self.addCleanup(unit.release)
            ingest(cfg, 1000)
            before = {p: p.read_bytes() for p in cfg.leases().iterdir()}
            ports = Ports(store=lambda repo: FakeBeadStore(), resource_holders=resource_holders)
            snap = Dash(Env(config=cfg.root, home=root, ports=ports, clock=lambda: 1000)).reads.snapshot()
            got = [(r.name, r.holder, r.run, r.project) for r in snap.leases]
            self.assertEqual(got, [("unity", "owner:unity-check", run.run, loop_key(repo))])
            self.assertEqual({p: p.read_bytes() for p in cfg.leases().iterdir()}, before)
