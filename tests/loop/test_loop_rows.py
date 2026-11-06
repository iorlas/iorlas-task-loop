"""The loop's state is a `lease` row in factory.db (tl-sqd3.26.1): written whole, read back, adopted from an older loop's file once,
and renamed `died-` when its pid is gone."""
import support.paths  # noqa: F401
from support import looptest

from loop.test_loop import LoopBase
from taskloop.contracts.loop import LoopState
from taskloop.contracts.stores import JsonStore


class LoopRowsTest(LoopBase):
    def state(self, pid: int) -> LoopState:
        return LoopState(pid=pid, started=10.0 + pid, t=11.0, repo=str(self.repo), version="1", code_dir="/c", actor="loop")

    def test_a_state_written_reads_back_and_goes_with_remove(self):
        files = looptest.files(str(self.repo))
        files.write(self.state(1))
        assert files.read(1) == self.state(1)
        files.remove(1)
        assert files.read(1) is None

    def test_an_older_loops_state_file_is_adopted_into_the_database_and_removed(self):
        files = looptest.files(str(self.repo))
        old = files.cfg.loop_state(f"{files.key}.55")
        JsonStore(old, LoopState).write(self.state(55))
        files.pid_alive = lambda _: True
        assert [st.pid for st in files.live()] == [55]
        assert not old.exists()
        assert files.read(55) == self.state(55)

    def test_a_dead_pid_becomes_a_died_row_and_is_not_live_again(self):
        files = looptest.files(str(self.repo))
        files.write(self.state(7))
        files.pid_alive = lambda _: False
        assert files.live() == [] and [st.pid for st in files.died()] == [7]
        assert files.live() == []
