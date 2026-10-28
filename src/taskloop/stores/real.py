"""The file-backed Stores of one process: everything under one ConfigDir."""
from taskloop.contracts import paths, stores
from taskloop.contracts.ask import Ask
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.stores.books import AskBook, CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.filelock import FileLockTable
from taskloop.stores.files import FileDocSet, FileTickets


def real_stores(cfg: paths.ConfigDir) -> Stores:
    return Stores(
        run_log=lambda run: stores.RunLog(cfg, run), events=stores.EventLog(cfg), traces=stores.TraceStore(cfg),
        asks=AskBook(FileDocSet(cfg.ask, Ask)), checkpoints=CheckpointBook(FileDocSet(cfg.checkpoint, Checkpoint)),
        loop_state=lambda key: stores.LoopStateStore(cfg, key),
        loop_command=lambda key: stores.LoopCommandStore(cfg, key),
        loop_rest=lambda key: stores.RestStore(cfg, key),
        locks=FileLockTable(cfg), tickets=FileTickets(cfg))
