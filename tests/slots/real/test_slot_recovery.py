"""A deleted slot is recreated through reset and claim preparation, despite its stale git registration."""
import contextlib
import shutil
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads
from support.fake_loop_env import slot_loop_env

from slots.real.test_worktrees import Rig, git
from taskloop.app.loop.take import Taker
from taskloop.app.slots.env import SlotEnv
from taskloop.app.slots.pool import SlotPool
from tlkernel.config import SlotsConfig
from tltestkit.memdoc import MemTickets


class SlotRecovery(Rig):
    def test_reset_and_claim_recreate_a_missing_registered_slot(self):
        setup = mock.Mock(return_value=0)
        env = SlotEnv(
            repo=self.repo, repo_key="r-1", cfg=SlotsConfig(setup=["setup"], setup_inputs=["a.txt"]), store=FakeBeads(), git=self.git,
            tickets=MemTickets(), cfgdir=self.cfg, actor="tl-test", host="h", take_lock=contextlib.nullcontext,
            busy=lambda _path: "", drop_engine_lock=lambda _path, _pid: None, event=lambda *_args, **_kw: None,
            run_setup=setup, exclude_local=lambda _repo: None, say=self.out.append, warn=self.out.append)
        slot = SlotPool(env).named("s1")
        slot.ready_for("")
        shutil.rmtree(slot.dir)
        slot.ready_for("")
        assert Path(slot.dir, "a.txt").exists()
        assert git(slot.dir, "rev-parse", "HEAD") == git(self.repo, "rev-parse", "origin/main")
        shutil.rmtree(slot.dir)
        taker = Taker(slot_loop_env(env), mock.Mock(), mock.Mock(),
                      mock.Mock(), mock.Mock(), {})
        assert taker.prepare("s1", "a") is None
        assert Path(slot.dir, "a.txt").exists()
        assert git(slot.dir, "branch", "--show-current") == "task/a"
        assert setup.call_count == 3  # old matching setup stamps cannot skip setup in a recreated tree
