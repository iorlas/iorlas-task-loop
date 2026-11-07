"""The Spawner contract, one suite for every implementation: RealSpawner over real processes (`sh -c`) and the same adapter over the
procsim (tests/support/procsim.py, which answers a registered command in process). A subclass sets `command` (the argv of a child that
prints `out` and exits with `code`, or hangs past any limit) and gets every test."""
from support.tags import contract  # noqa: F401  (re-exported for the subclasses)

from taskloop.adapters.spawner import RealSpawner
from tlkernel.env import snapshot
from tlkernel.procport import Spawner
from tltestkit.case import Case

_Base = Case


class SpawnerContract(_Base):
    __test__ = False

    def command(self, code: int = 0, out: str = "", hang: bool = False) -> list[str]:
        raise NotImplementedError

    def make(self) -> Spawner:
        return RealSpawner(snapshot())

    def test_run_returns_the_exit_and_the_output(self):
        r = self.make().run(self.command(3, "hi"))
        assert (r.exit, r.out, r.timed_out) == (3, "hi", False)

    def test_run_of_a_clean_child_is_exit_zero(self):
        r = self.make().run(self.command(0, "ok"))
        assert (r.exit, r.out, r.timed_out) == (0, "ok", False)

    def test_run_past_its_timeout_is_exit_124_and_timed_out(self):
        r = self.make().run(self.command(hang=True), timeout_s=0.3)
        assert (r.exit, r.timed_out) == (124, True)

    def test_run_bytes_returns_the_exit_and_the_output_bytes(self):
        r = self.make().run_bytes(self.command(2, "by"))
        assert (r.exit, r.out) == (2, b"by")

    def test_stream_hands_each_line_over_and_reports_how_it_ended(self):
        chunks: list[str] = []
        r = self.make().stream(self.command(3, "hi\n"), on_output=chunks.append)
        assert ("".join(chunks), r.returncode, r.signal, r.timed_out) == ("hi\n", 3, None, None)

    def test_stream_past_its_timeout_is_a_wall_stop_with_no_exit_code(self):
        r = self.make().stream(self.command(hang=True), on_output=lambda s: None, timeout_s=0.3)
        assert (r.timed_out, r.returncode) == ("wall", None)
