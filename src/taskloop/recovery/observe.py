"""Read native identities through the owning process APIs, without starting or stopping anything."""

from taskloop import owned_processes
from taskloop.attempt_types import EntryIdentity
from taskloop.drain.models import Identity, Seen
from taskloop.recovery.models import ProcessObservation


class NativeProcesses:
    def entry(self, identity: EntryIdentity) -> ProcessObservation:
        seen = owned_processes.entry_seen(identity)
        state = Seen.GONE if seen in ("gone", "different_process") else Seen.ALIVE if seen == "matching" else Seen.UNKNOWN
        return ProcessObservation(seen=state, explanation=f"The registered entry identity is {state.value}.")

    def process(self, identity: Identity) -> ProcessObservation:
        if owned_processes.current_boot() is None:
            return ProcessObservation(seen=Seen.UNKNOWN, explanation="The current boot identity cannot be confirmed.")
        state = Seen(owned_processes.setup_seen(identity.owned()))
        return ProcessObservation(seen=state, explanation=f"The registered process and its group are {state.value}.")
