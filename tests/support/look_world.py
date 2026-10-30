"""An owner-look bead in memory: items in metadata `looks`, bd faked with the writes it receives recorded."""
from support.fake_beads import FakeBeads
from taskloop.contracts import gallery
from taskloop.contracts.bead import BdError, Bead
from taskloop.contracts.ports import BdFailure


def shots(label="menu"):
    return [{"path": f"docs/evidence/tl-1/{label}-before.png", "role": "before", "label": label},
            {"path": f"docs/evidence/tl-1/{label}.png", "role": "after", "label": label}]


def looks(*statuses):
    return [
        {
            "id": f"tl-1#{int(k)}",
            "bead": "tl-1",
            "title": f"menu reads well {int(k)}",
            "note": "judge: fine",
            "shots": shots(f"m{int(k)}"),
            "status": s,
        }
        for k, s in enumerate(statuses, 1)
    ]


class FakeBd(FakeBeads):
    """The typed bd port in memory, with the writes the gallery makes recorded in `calls` and `refuse` naming writes that fail."""

    def __init__(self, beads):
        super().__init__(prefix="tl-r")
        self.beads = {k: Bead(**v) for k, v in beads.items()}
        self.calls, self.refuse = [], set()

    def _try(self, what, bead):
        self.calls.append((what, bead))
        if what in self.refuse:
            raise BdFailure(BdError(kind="other", text="boom"))

    def update(self, bead, patch):
        self._try("update-meta" if patch.metadata is not None and bead == "tl-look" else "update", bead)
        super().update(bead, patch)

    def close(self, bead, reason, if_assignee=""):
        self._try("close", bead)
        super().close(bead, reason, if_assignee)

    def create(self, new):
        self._try("create", "")
        return super().create(new)


def world(*statuses, status="open"):
    return FakeBd({"tl-look": {"id": "tl-look", "title": "Look review", "status": status, "labels": [gallery.LABEL],
                               "metadata": {"looks": looks(*statuses), "other": 1}}})
