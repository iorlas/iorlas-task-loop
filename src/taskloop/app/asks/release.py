"""A bead the engine woke by answering its ask: open again, with the pick label the park took off given back."""
from tlkernel.askstore import HAD_PICK
from tlkernel.bead import Bead
from tlkernel.beadsport import BeadPatch, Beads
from tlkernel.config import EngineConfig
from tlkernel.ids import BeadId


def requeue(store: Beads, bead: BeadId, shown: Bead, cfg: EngineConfig) -> None:
    store.update(bead, BeadPatch(status="open"))
    pick, info = cfg.pick_label or "", cfg.needs_info_label or ""
    if pick and shown.metadata.get(HAD_PICK) == pick:
        store.add_label(bead, pick)
        store.update(bead, BeadPatch(unset_metadata=[HAD_PICK]))
    if info and info in shown.labels:
        store.remove_label(bead, info)
