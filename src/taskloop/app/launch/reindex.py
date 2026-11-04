"""Launch the dashboard's one-shot indexer for `tl doctor --reindex`."""

from taskloop.contracts import factorybackup
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.index import reindex


def run(cfg: ConfigDir) -> int:
    damage = factorybackup.damaged(cfg)
    restored = factorybackup.restore(cfg)
    if restored is not None:
        print(f"restored factory.db from {restored}")
    elif damage:
        print("factory.db was damaged and no backup exists; rebuilding from retained files")
    counts = reindex(cfg)
    print(f"reindexed: {counts['run']} runs, {counts['source']} sources in {counts['seconds']:.3f}s")
    return 0
