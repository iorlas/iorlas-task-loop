"""Launch the dashboard's one-shot indexer for `tl doctor --reindex`."""

from tlkernel import factorybackup
from tlkernel.paths import ConfigDir

from taskloop.app.launch.dash_ports import store
from taskloop_dash.env import Env, Ports
from taskloop_dash.index import reindex
from taskloop_dash.readers.records import Records


def run(cfg: ConfigDir) -> int:
    damage = factorybackup.damaged(cfg)
    restored = factorybackup.restore(cfg)
    if restored is not None:
        print(f"restored factory.db from {restored}")
    elif damage:
        print("factory.db was damaged and no backup exists; rebuilding empty (the run files are no longer a source)")
    records = Records(Env(cfg.root, ports=Ports(store=store)))
    counts = reindex(cfg, repos=records.repos, store_of=store)
    print(f"reindexed: {counts['run']} runs, {counts['source']} sources in {counts['seconds']:.3f}s")
    return 0
