"""The `show` class, checked mechanically (tl-jvpm.25): after the last stage's write, every artifact a show case names (file name and
role) must be in the artifact store for this write's attempt. A miss goes back to the writer once as a retry reason; it never parks."""
from pathlib import Path

from tlkernel.artifact import ArtifactSlot
from tlkernel.plancheck import Open

from taskloop.app.artifacts import store
from taskloop.domain.work import visual

SHOW_BACK = ("\nThe plan's `show` items name pictures or files that must be registered with the artifact_add tool for this write, with "
             "the stated name and role. These are not registered:\n%s\nRegister each one (the tool says what is wrong with a file), "
             "then answer again.")


def slot_of(repo: str, bead: str, run: str, write: int) -> ArtifactSlot:
    """Where the artifacts of one write land: stage `write`, the attempt is the stage's write counter."""
    return ArtifactSlot(repo=repo, bead=bead, run=run, stage="write", attempt=write)


def missing(cases: list[Open], root: Path, slot: ArtifactSlot) -> list[str]:
    """The show items of the plan whose named artifacts are not registered in the slot's folder, one line each."""
    if not any(c.get("class") == "show" for c in cases):
        return []
    have = {(m.name, m.role) for m in store.listing(store.folder(root, slot))}
    return visual.unmet_shows(cases, have)
