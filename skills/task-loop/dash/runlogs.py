"""The engine-log views for the old dashboard server: one FileCache and a thin namespace over taskloop_dash.views. Goes with
server.py when it moves into the package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from taskloop.contracts import log as rec  # noqa: E402
from taskloop_dash.cache import FileCache  # noqa: E402
from taskloop_dash.views import detail, names, segments  # noqa: E402
from taskloop_dash.views import timeline as tlv  # noqa: E402

FILES = FileCache()


class timeline:  # noqa: N801  (the old module's name for the engine-log views, now one thin namespace over taskloop_dash.views)
    run_name, bead_of, lane_name, when = staticmethod(names.run_name), staticmethod(names.bead_of), staticmethod(names.lane_name), staticmethod(names.when)
    because_text, live_label = staticmethod(tlv.because_text), staticmethod(tlv.live_label)
    bead_segments = staticmethod(segments.bead_segments)

    @staticmethod
    def read(path):
        return tlv.read(path, FILES)

    @staticmethod
    def run_timeline(path, alive=False, now=None):
        return tlv.run_timeline(path, alive=alive, now=now, cache=FILES)

    @staticmethod
    def last_node(path):
        return tlv.last_node(path, FILES)


def run_timeline(path, alive=False, now=None):
    return timeline.run_timeline(path, alive, now)


def block_detail(path, node_id, k=0):
    return detail.block_detail(path, node_id, k, FILES)


def run_facts(recs):
    """(the run's start as {worktree, slot} or None, whether a close record is among the last 40)."""
    start = next((r for r in recs if isinstance(r, rec.RunStart)), None)
    return ({"worktree": start.worktree, "slot": start.slot or ""} if start else None), any(isinstance(r, rec.Close) for r in recs[-40:])
