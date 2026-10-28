"""Filing the follow-up beads of a run at its close: through the engine's bd (`create_checked`), one `from:` label, no inherited labels,
at most FOLLOW_UP_CAP, the rest in one comment on the source bead."""
from collections.abc import Mapping, Sequence
from typing import Any

from taskloop.contracts.ports import NewBead
from taskloop.domain.review import followups as fu


def named(los: Sequence[Mapping[str, str]]) -> str:
    return "; ".join(f"{lo['title']} ({lo['why'][:120]})" for lo in los)


def file_follow_ups(e: Any) -> list[dict[str, str]]:
    """-> the ones bd refused. A kill after a create loses no key: the checkpoint follows each one."""
    todo = fu.batch(e.bead, e.leftovers, e.filed)
    tag = fu.label(e.bead, e.stats["rounds"])
    unfiled: list[dict[str, str]] = []
    for lo in todo.file:
        made, err = e.create_checked(NewBead(title=lo["title"], description=lo["why"], deps=["discovered-from:" + e.bead],
                                             labels=[tag], no_inherit_labels=True))
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
