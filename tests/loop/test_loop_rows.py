"""The loop's state is a `lease` row in factory.db (tl-sqd3.26.1): written whole, read back,
and renamed `died-` when its pid is gone."""
import support.paths  # noqa: F401
from support import looptest

from loop.test_loop import LoopBase
from taskloop.contracts.loop import LoopCommand, LoopState, LoopTarget, Rest


class LoopRowsTest(LoopBase):
    def state(self, pid: int) -> LoopState:
        return LoopState(pid=pid, started=10.0 + pid, t=11.0, repo=str(self.repo), version="1", code_dir="/c", actor="loop")

    def test_a_state_written_reads_back_and_goes_with_remove(self):
        files = looptest.files(str(self.repo))
        files.write(self.state(1))
        assert files.read(1) == self.state(1)
        files.remove(1)
        assert files.read(1) is None

    def test_a_dead_pid_becomes_a_died_row_and_is_not_live_again(self):
        files = looptest.files(str(self.repo))
        files.write(self.state(7))
        files.pid_alive = lambda _: False
        assert files.live() == [] and [st.pid for st in files.died()] == [7]
        assert files.live() == []

    def test_the_stop_command_and_the_rests_are_rows(self):
        files = looptest.files(str(self.repo))
        old = LoopCommand(action="stop_now", by="t", t=1.0, targets=[LoopTarget(pid=5, started=2.0)])
        files.command().write(old)
        files.rest_doc().write(Rest(beads={"b-1": 1e12}))
        assert files.command().get() == old and files.rests() == {"b-1": 1e12}
        files.command().delete()
        assert files.command().get() is None
