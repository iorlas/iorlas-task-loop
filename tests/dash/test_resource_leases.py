"""The Floor reads resource holder hints through ConfigDir without taking or changing a lock."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.factory_index import ingest
from support.fakes import FakeBeadStore
from support.repos import write_repos

from taskloop.adapters.locks import holder_file, resource_holders
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.ids import loop_key
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.locks import LockRecord
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import JsonStore
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports


class Leases(unittest.TestCase):
    def test_held_free_and_dead_leases_are_read_only_and_joined_to_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg, repo = ConfigDir(root / "cfg"), root / "project"
            repo.mkdir()
            cfg.root.mkdir()
            write_repos(cfg.repos(), repo)
            run = RunLocator(cfg).create(str(repo), "", 1000, mode="stage:check")
            held = cfg.lock_record("resource", "unity-0")
            dead = cfg.lock_record("resource", "unity-1")
            free = cfg.lock_record("resource", "unity-2")
            held.parent.mkdir()
            held.write_text("held")
            free.write_text("")
            for path, pid in ((held, os.getpid()), (dead, 999999)):
                JsonStore(holder_file(path), LockRecord).write(
                    LockRecord(what=LockWhat.RESOURCE, holder="owner:unity-check", pid=pid, t=990))
            ingest(cfg, 1000)
            before = {p: p.read_bytes() for p in held.parent.iterdir()}
            ports = Ports(store=lambda repo: FakeBeadStore(), resource_holders=resource_holders)
            with patch("taskloop.contracts.locks.pid_alive", side_effect=lambda pid: pid == os.getpid()):
                snap = Dash(Env(config=cfg.root, home=root, ports=ports, clock=lambda: 1000)).reads.snapshot()
            self.assertEqual([(r.name, r.holder, r.since, r.run, r.project) for r in snap.leases],
                             [("unity", "owner:unity-check", 990, run.run, loop_key(repo))])
            self.assertEqual({p: p.read_bytes() for p in held.parent.iterdir()}, before)
