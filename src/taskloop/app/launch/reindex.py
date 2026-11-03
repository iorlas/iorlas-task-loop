"""Launch the dashboard's one-shot indexer for `tl doctor --reindex`."""

from taskloop.contracts.paths import ConfigDir
from taskloop_dash.index import reindex


def run(cfg: ConfigDir) -> int:
    counts = reindex(cfg)
    print(f"reindexed: {counts['run']} runs, {counts['source']} sources in {counts['seconds']:.3f}s")
    return 0
