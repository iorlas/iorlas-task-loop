"""A starting loop prunes the loop logs; a sibling lane's log that vanishes or dangles never crashes it (tl-nhys)."""
import os
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

from taskloop.app.loop.core import prune_logs


class PruneLogs(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runs = Path(tmp.name)

    def log(self, pid: int, age: int) -> Path:
        f = self.runs / f"loop-{pid}.log"
        f.write_text("x")
        os.utime(f, (1000 + age, 1000 + age))
        return f

    def names(self) -> list[str]:
        return sorted(f.name for f in self.runs.glob("loop-*.log"))

    def test_the_newest_stay_and_the_own_log_is_never_listed_for_removal(self):
        for i in range(8):
            self.log(100 + i, i)
        own = self.runs / "loop-1.log"
        prune_logs(self.runs, own, 5)
        assert self.names() == ["loop-104.log", "loop-105.log", "loop-106.log", "loop-107.log"]  # four old ones and the loop's own to come

    def test_a_dead_link_from_a_lane_that_pruned_a_log_does_not_raise(self):
        self.log(200, 1)
        (self.runs / "loop-201.log").symlink_to(self.runs / "loop-gone.log")
        prune_logs(self.runs, self.runs / "loop-1.log", 5)
        assert self.names() == ["loop-200.log"]
