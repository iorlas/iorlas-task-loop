"""The file-backed Stores of one process: everything under one ConfigDir."""
from any_lease import Leases

from taskloop.adapters.locks import ProcessLockTable
from taskloop.stores.books import CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.profile_changes import profile_changes
from taskloop.stores.ticketrows import TicketRows
from tlkernel import paths, rundocs, stores
from tlkernel.adrs import AdrStore
from tlkernel.askstore import AskStore
from tlkernel.checkpoint import Checkpoint
from tlkernel.checks import BaseRedRecord, CheckRun, PassRecord
from tlkernel.config import HostResources
from tlkernel.docrows import FLAKE_DOCS, QUEUE_DOCS, RowDocs
from tlkernel.docstore import JsonStore
from tlkernel.flakes import FlakeLog
from tlkernel.followups import FollowupOutbox
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.receiptrows import DbDocSet


def real_stores(cfg: paths.ConfigDir) -> Stores:
    return Stores(
        run_log=lambda run: stores.RunLog(cfg, run), events=stores.EventLog(cfg), traces=stores.TraceStore(cfg),
        profile_changes=profile_changes(cfg),
        asks=AskStore.at(cfg), adrs=lambda repo: AdrStore.at(cfg, repo),
        checkpoints=CheckpointBook(RowDocs(cfg, Checkpoint, table="checkpoint", key_col="bead", body_col="body",
                                           revisioned=True)),
        followups=RowDocs(cfg, FollowupOutbox, table="followup", key_col="bead", body_col="body"),
        flakes=RowDocs(cfg, FlakeLog, table=FLAKE_DOCS, key_col="k", body_col="v", prefix="flakes:"),
        queue=RowDocs(cfg, QueueDoc, table=QUEUE_DOCS, key_col="k", body_col="v", prefix="queue:"),
        queue_state=RowDocs(cfg, QueueState, table=QUEUE_DOCS, key_col="k", body_col="v", prefix="queue-state:"),
        results=lambda repo, check: DbDocSet(cfg, repo, check, "pass", PassRecord),
        base_red=lambda repo: DbDocSet(cfg, repo, None, "base_red", BaseRedRecord),
        durations=rundocs.durations(cfg),
        check_run=lambda run, rnd: JsonStore(cfg.check_run(run, rnd), CheckRun),
        host=JsonStore(cfg.host(), HostResources), locks=ProcessLockTable(cfg), leases=Leases(cfg.leases()), tickets=TicketRows(cfg))
