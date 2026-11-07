"""Reset diagnostics never repair a released slot; branch freeing checks fresh ownership."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from git_porcelain.errors import GitUnavailable

from taskloop.adapters.git import RealGit
from tlkernel.env import Env
from tlslots.testing import Rig


class ResetOwnership(Rig):
    def test_failed_status_in_ready_for_preserves_work_and_refuses_all_mutations(self):
        work = Path(self.d1) / "untracked.txt"
        work.write_text("keep me")
        adapter = RealGit(Env(), pinned=False)
        with (mock.patch.object(adapter, "_pool", side_effect=GitUnavailable("status unavailable")),
              mock.patch.object(self.git, "dirty", side_effect=adapter.dirty),
              mock.patch("tlslots.reset.setup") as setup):
            assert self.code(lambda: self.slot().ready_for("x-1")) == "transient"
        setup.assert_not_called()
        assert work.read_text() == "keep me"
        assert [call[0] for call in self.git.calls] == ["rebasing"]
