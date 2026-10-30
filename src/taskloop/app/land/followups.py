"""Filing the follow-up beads of a run at its close: through the engine's bd (`create_checked`), one `from:` label, no inherited labels,
at most FOLLOW_UP_CAP, the rest in one comment on the source bead."""
from collections.abc import Mapping, Sequence
from typing import Protocol

from taskloop.adapters import bdcreate
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads, NewBead
from taskloop.domain.review import followups as fu
from taskloop.stores.runlog import RunLog


class FollowUpCheckpoints(Protocol):
    def keep_filed(self, lost: list[dict[str, str]] | None = ...) -> None: ...


class FollowUpHost(Protocol):
    """What filing follow-ups reads of the engine: the bead, the leftovers and the keys filed so far, bd, the poster, the log."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def store(self) -> Beads: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def filed(self) -> list[str]: ...
    @property
    def checkpoints(self) -> FollowUpCheckpoints: ...

    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...


def named(los: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{lo['title']} ({lo['why'][:120]})" for lo in los)


def already(e: FollowUpHost, lo: Mapping[str, str]) -> bool:
    """An open follow-up bead of an earlier run already carries this bead's unchecked items."""
    try:
        rows = e.store.find(BeadQuery(label=fu.TAG))
    except BdFailure:
        return False
    return any(r.title.startswith(fu.title_prefix(e.bead)) for r in rows)


def file_follow_ups(e: FollowUpHost) -> list[dict[str, str]]:
    """-> the ones bd refused. A kill after a create loses no key: the checkpoint follows each one."""
    todo = fu.batch(e.bead, e.leftovers, e.filed)
    unfiled: list[dict[str, str]] = []
    for lo in todo.file:
        if lo.get("category") == fu.UNCHECKED and already(e, lo):
            e.filed.append(str(fu.FollowKey.of(e.bead, lo)))  # an earlier run filed it
            continue
        made, err = bdcreate.create_checked(e.store, NewBead(title=lo["title"], description=lo["why"], deps=["discovered-from:" + e.bead],
                                             labels=fu.labels(e.bead, e.stats["rounds"], lo), no_inherit_labels=True), e.bead, e.log.note)
        if made:
            e.filed.append(str(fu.FollowKey.of(e.bead, lo)))
            e.checkpoints.keep_filed()
        else:
            unfiled.append(dict(lo))
            e.warn(f"follow-up not filed: {lo['title'][:80]}: {err[:200]}")
    if unfiled:
        e.comment(f"Follow-up (engine): bd refused {len(unfiled)} follow-up(s), none was filed: {named(unfiled)}")
        e.checkpoints.keep_filed(unfiled)
    if todo.over:
        e.comment(f"Follow-up (engine): not filed, the cap is {fu.FOLLOW_UP_CAP} per run; {len(todo.over)} more: {named(todo.over)}")
    return unfiled
