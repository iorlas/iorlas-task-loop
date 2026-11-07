"""Filing the follow-up beads of a run at its close: through the engine's bd (`create_checked`), one `from:` label, no inherited labels,
at most FOLLOW_UP_CAP, the rest in one comment on the source bead."""
from collections.abc import Mapping, Sequence
from typing import Protocol

from taskloop.adapters import bdcreate
from taskloop.app.asks import deferral as intake
from taskloop.contracts.beadsport import BdFailure, BeadQuery, Beads, NewBead
from taskloop.contracts.ids import BeadId
from taskloop.domain import followups as fu
from taskloop.stores.runlog import RunLog

class FollowUpCheckpoints(Protocol):
    def keep_filed(self, lost: list[dict[str, str]] | None = ...) -> None: ...
    def keep_pending(self, origin: str = ...) -> None: ...


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
    def followup_ids(self) -> dict[str, str]: ...
    @property
    def checkpoints(self) -> FollowUpCheckpoints: ...
    @property
    def intake_per_day(self) -> int: ...

    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...


def named(los: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{lo['title']} ({lo['why'][:120]})" for lo in los)


def file_follow_ups(e: FollowUpHost) -> list[dict[str, str]]:
    """-> the ones bd refused. Resolve the bead's exact key before creating, including closed beads."""
    e.checkpoints.keep_pending()
    todo = fu.batch(e.bead, e.leftovers, e.filed)
    unfiled: list[dict[str, str]] = []
    for lo in todo.file:
        key = str(fu.FollowKey.of(e.bead, lo))
        try:
            rows = e.store.find(BeadQuery(label=fu.key_label(e.bead, lo), include_closed=True))
            made, err = (str(rows[0].id), "") if rows else bdcreate.create_checked(e.store, NewBead(
                title=lo["title"], description=lo["why"], deps=["discovered-from:" + e.bead],
                labels=fu.labels(e.bead, e.stats["rounds"], lo) + ([intake.FROM_REVIEW] if e.intake_per_day > 0 else []),
                no_inherit_labels=True), e.bead, e.log.note)
            if made and not rows and e.intake_per_day > 0:
                intake.defer(e.store, BeadId(made))
        except BdFailure as failure:
            made, err = "", failure.error.text  # an unavailable lookup is never permission to create a duplicate
        if made:
            e.filed.append(key)
            e.followup_ids[key] = made
            e.checkpoints.keep_filed()
        else:
            unfiled.append(dict(lo))
            e.warn(f"follow-up not filed: {lo['title'][:80]}: {err}")
    if unfiled:
        e.comment(f"Follow-up (engine): bd refused {len(unfiled)} follow-up(s), none was filed: {named(unfiled)}")
        e.checkpoints.keep_filed(unfiled)
    if todo.over:
        e.comment(f"Follow-up (engine): not filed, the cap is {fu.FOLLOW_UP_CAP} per run; {len(todo.over)} more: {named(todo.over)}")
        e.warn(f"{len(todo.over)} follow-up(s) remain in the durable outbox beyond this run's cap")
    return unfiled
