"""The file-backed Stores of one process: everything under one ConfigDir."""
from any_lease import Leases

from taskloop.adapters.locks import ProcessLockTable
from taskloop.contracts import paths, stores
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.checks import BaseRedRecord, CheckRun, Durations, PassRecord
from taskloop.contracts.config import HostResources
from taskloop.contracts.docrows import RowDocs
from taskloop.contracts.followups import FollowupOutbox
from taskloop.contracts.receiptrows import DbDocSet
from taskloop.contracts.stores import AskStore, JsonStore
from taskloop.stores.books import CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.files import FileDocSet, FileTickets
from taskloop.stores.profile_changes import profile_changes


def real_stores(cfg: paths.ConfigDir) -> Stores:
    return Stores(
        run_log=lambda run: stores.RunLog(cfg, run), events=stores.EventLog(cfg), traces=stores.TraceStore(cfg),
        profile_changes=profile_changes(cfg),
        asks=AskStore.at(cfg), adrs=lambda repo: AdrStore.at(cfg, repo),
        checkpoints=CheckpointBook(RowDocs(cfg, Checkpoint, cfg.checkpoint, table="checkpoint", key_col="bead", body_col="body",
                                           revisioned=True)),
        followups=RowDocs(cfg, FollowupOutbox, cfg.followup_outbox, table="kv", key_col="k", body_col="v", prefix="followup:"),
        loop_state=lambda key: stores.LoopStateStore(cfg, key),
        loop_command=lambda key: stores.LoopCommandStore(cfg, key),
        loop_rest=lambda key: stores.RestStore(cfg, key),
        results=lambda repo, check: DbDocSet(cfg, repo, check, "pass", PassRecord),
        base_red=lambda repo: DbDocSet(cfg, repo, None, "base_red", BaseRedRecord),
        durations=FileDocSet(cfg.check_durations, Durations),
        check_run=lambda run, rnd: JsonStore(cfg.check_run(run, rnd), CheckRun),
        host=JsonStore(cfg.host(), HostResources), locks=ProcessLockTable(cfg), leases=Leases(cfg.leases()), tickets=FileTickets(cfg))
