"""The beads the brief golden set renders: every section, none, the engine's own lines, owner_only and the linked beads."""

from tlkernel.bead import Bead, Comment, Dep
from tlkernel.ids import BeadId

FULL = Bead(
    id=BeadId("t-1"), title="Add f", status="", issue_type="feature", priority=1,
    labels=["needs-owner-check", "tl-pick", "ui"],
    description="Add the file f.\nSecond line.", acceptance_criteria="f.txt exists\n- and is tracked",
    design="Keep it small.", notes="owner: keep it short\nEngine paused: waiting for a person\nEngine failed: boom",
    metadata={"owner_hint": " use the old format "},
    dependencies=[Dep(id="t-0", title="The epic", status="open", type="blocks"),
                  Dep(id="t-5", title="Other é", type="related")],
)
BARE = Bead(id=BeadId("t-2"), title="Only a title", status="")
COMMENTS = [{"author": "tl-a", "text": "Plan (engine): " + "p" * 300}, {"author": "denis", "text": "Use the old format.\nPlease."},
            {"author": "", "text": "  second note  "}, {"author": "tl-a", "text": "Blocked: failed: stopped"}]
CASES: dict[str, tuple[Bead, list[dict[str, str]], bool]] = {
    "full": (FULL, COMMENTS, False),
    "full_owner_only": (FULL, COMMENTS, True),
    "bare": (BARE, [], False),
    "bare_with_comments": (BARE, COMMENTS, False),
}


def beads(name: str) -> tuple[Bead, list[Comment], bool]:
    bead, comments, owner_only = CASES[name]
    return bead, [Comment(author=c["author"], text=c["text"]) for c in comments], owner_only
