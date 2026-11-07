"""Shell store bundle assembled from in-memory test-kit stores."""
from support.memcheckpoints import MemCheckpointRows
from taskloop.stores.books import CheckpointBook
from taskloop.stores.bundle import Stores
from taskloop.stores.files import temp_leases
from tlkernel import events, log
from tlkernel.adrs import AdrStore
from tlkernel.ask import Ask
from tlkernel.askstore import AskStore
from tlkernel.checks import BaseRedRecord, CheckRun, Durations, PassRecord
from tlkernel.config import HostResources
from tlkernel.flakes import FlakeLog
from tlkernel.followups import FollowupOutbox
from tlkernel.ledger import Adr, AdrUse, LedgerEntry
from tlkernel.profile_changes import ProfileChange
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.trace import RunTrace
from tltestkit.memdoc import MemDoc, MemDocSet, MemLockTable, MemLog, MemTickets, _decode


def fake_stores(pid: int | None = None) -> Stores:
    """A whole fake process environment: nothing touches the disk."""
    runs: dict[str, MemLog[log.EngineLog]] = {}
    check_runs: dict[tuple[str, int | None], MemDoc[CheckRun]] = {}
    adrs: dict[str, AdrStore] = {}
    passes: dict[tuple[str, str], MemDocSet[PassRecord]] = {}
    reds: dict[str, MemDocSet[BaseRedRecord]] = {}
    return Stores(
        run_log=lambda run: runs.setdefault(run, MemLog(log.decode)),
        events=MemLog(events.decode), traces=MemLog(_decode(RunTrace)),
        profile_changes=MemLog(_decode(ProfileChange)),
        asks=AskStore(MemDocSet(Ask), MemLog(_decode(LedgerEntry))),
        adrs=lambda repo: adrs.setdefault(repo, AdrStore(MemDocSet(Adr), MemLog(_decode(AdrUse)))),
        checkpoints=CheckpointBook(MemCheckpointRows()),
        flakes=MemDocSet(FlakeLog),
        followups=MemDocSet(FollowupOutbox), queue=MemDocSet(QueueDoc), queue_state=MemDocSet(QueueState),
        results=lambda repo, check: passes.setdefault((repo, check), MemDocSet(PassRecord)),
        base_red=lambda repo: reds.setdefault(repo, MemDocSet(BaseRedRecord)),
        durations=MemDocSet(Durations),
        check_run=lambda run, rnd: check_runs.setdefault((run, rnd), MemDoc(CheckRun)),
        host=MemDoc(HostResources), locks=MemLockTable(pid), leases=temp_leases(), tickets=MemTickets())
