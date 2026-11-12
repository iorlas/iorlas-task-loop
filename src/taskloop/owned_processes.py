"""Native process-table observations (stream_proc) of the processes the factory registered: the agent, a setup command,
the attempt entry, and this machine's boot. No spawn or signal. Wired by `composition`."""

import os

from any_agent.procs import Worker
from stream_proc import OwnedProcess, group_alive, inspect_process, observe_owned

from taskloop.attempt_types import EntryIdentity, Seen, entry_identity
from taskloop.launch import entry_process
from taskloop.setup_store import ProcessSeen


def worker_gone(worker: Worker) -> bool:
    """The registered agent process is gone (or its pid now names another process) and no process is left in its
    process group: the library's identity read and `killpg(pgid, 0)`. Unknown counts as alive. The agent's shell commands
    run outside that group by design, each in a new session under `bwrap --unshare-pid --as-pid-1 --die-with-parent`:
    that PID namespace contains them and ends when its parent ends (Run S finding 6, Linux, codex 0.167.0), so this is
    their stop proof too. Setup processes are never in the agent's group (the entry proves each command's group empty
    before dispatch; the release proves an unsettled setup gone). Not a stop proof for descendants that leave the group
    otherwise (.4.4)."""
    seen = observe_owned(OwnedProcess(worker.pid, worker.pgid, worker.start, worker.boot)).kind
    return seen in ("gone", "different_process") and not group_alive(worker.pgid)


def setup_seen(process: OwnedProcess) -> ProcessSeen:
    """A registered setup command, as `worker_gone` observes an agent: alive while its identity matches or a process is
    left in its group, unknown when the process table cannot be read; one from another boot is gone (its group id names
    nothing of it now). Never signalled."""
    seen = observe_owned(process).kind
    if seen in ("matching", "unknown"):
        return "alive" if seen == "matching" else "unknown"
    if current_boot() != process.boot:
        return "gone"
    return "alive" if group_alive(process.pgid) else "gone"


def entry_seen(entry: EntryIdentity) -> Seen:
    """A native process-table read of the registered entry, by the launcher's identity rule; no spawn or signal."""
    return observe_owned(entry_process(entry)).kind


def this_process() -> EntryIdentity | None:
    """This process's own native identity (pid, start, boot), as a registered entry's is read: the land process's, written
    on its candidate while it holds the slot's custody (tl-8bh9.14.8 section 6); None when it cannot be read."""
    seen = inspect_process(os.getpid())
    found = seen.identity
    return None if seen.kind != "matching" or found is None else entry_identity(found)


def current_boot() -> str | None:
    """This machine's boot id, as a registered entry's identity carries it: this process's own native identity read
    through the library's public inspection (no spawn or signal); None when unknown."""
    seen = inspect_process(os.getpid()).identity
    return None if seen is None else seen.boot
