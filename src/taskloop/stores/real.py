"""The file-backed Stores of one process: everything under one ConfigDir."""
from taskloop.adapters.locks import ProcessLockTable
from taskloop.contracts import paths, stores
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.checks import CheckCacheEntry, CheckRun, Durations
from taskloop.contracts.config import HostResources
from taskloop.contracts.stores import AskStore, JsonStore
from taskloop.stores.books import CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.files import FileDocSet, FileTickets


def real_stores(cfg: paths.ConfigDir) -> Stores:
    return Stores(
        run_log=lambda run: stores.RunLog(cfg, run), events=stores.EventLog(cfg), traces=stores.TraceStore(cfg),
        asks=AskStore.at(cfg), adrs=lambda repo: AdrStore.at(cfg, repo),
        checkpoints=CheckpointBook(FileDocSet(cfg.checkpoint, Checkpoint)),
        loop_state=lambda key: stores.LoopStateStore(cfg, key),
        loop_command=lambda key: stores.LoopCommandStore(cfg, key),
        loop_rest=lambda key: stores.RestStore(cfg, key),
        check_cache=FileDocSet(cfg.check_cache, CheckCacheEntry), durations=FileDocSet(cfg.check_durations, Durations),
        check_run=lambda run, rnd: JsonStore(cfg.check_run(run, rnd), CheckRun),
        host=JsonStore(cfg.host(), HostResources), locks=ProcessLockTable(cfg), tickets=FileTickets(cfg))
