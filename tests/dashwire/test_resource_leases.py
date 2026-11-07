"""The Floor reads resource holder hints through ConfigDir without taking or changing a lock."""
import sys
import time
from pathlib import Path

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from any_lease import Leases
from support.factory_index import ingest
from support.fakes import FakeBeadStore

from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from tlkernel.ids import loop_key
from tlkernel.locator import RunLocator
from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord
from tlkernel.paths import ConfigDir
from tltestkit.repos import write_repos


class ResourceLeases(Case):
    def test_a_held_lease_is_read_only_and_joined_to_the_run(self):
        with TemporaryDirectory() as tmp:
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
            assert table.holders("unity")[0].holder.created == pytest.approx(time.time(), abs=5)  # type: ignore[union-attr]
            before = {p: p.read_bytes() for p in cfg.leases().iterdir()}
            holder = LockRecord(what=LockWhat.RESOURCE, holder="owner:unity-check", pid=run.manifest.pid, t=1000)
            ports = Ports(store=lambda repo: FakeBeadStore(), resource_holders=lambda cfg: [("unity", holder)])
            snap = Dash(Env(config=cfg.root, home=root, ports=ports, clock=lambda: 1000)).reads.snapshot()
            got = [(r.name, r.holder, r.run, r.project) for r in snap.leases]
            assert got == [("unity", "owner:unity-check", run.run, loop_key(repo))]
            assert {p: p.read_bytes() for p in cfg.leases().iterdir()} == before
