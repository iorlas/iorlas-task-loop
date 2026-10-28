"""The beads the brief golden set renders: every section, none, the engine's own lines, owner_only and the linked beads."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.bd import bead_of
from taskloop.contracts.bead import Bead, Comment

FULL = {"id": "t-1", "title": "Add f", "issue_type": "feature", "priority": 1, "labels": ["tl-pick", "ui", "needs-owner-check"],
        "description": "Add the file f.\nSecond line.", "acceptance_criteria": "f.txt exists\n- and is tracked",
        "design": "Keep it small.", "notes": "owner: keep it short\nEngine paused: waiting for a person\nEngine failed: boom",
        "metadata": {"owner_hint": " use the old format "},
        "dependencies": [{"id": "t-0", "title": "The epic", "status": "open", "type": "blocks"},
                         {"id": "t-5", "title": "Other é", "type": "related"}]}
BARE = {"id": "t-2", "title": "Only a title", "metadata": {}}
COMMENTS = [{"author": "tl-a", "text": "Plan (engine): " + "p" * 300}, {"author": "denis", "text": "Use the old format.\nPlease."},
            {"author": "", "text": "  second note  "}, {"author": "tl-a", "text": "Blocked: failed: stopped"}]
CASES = {
    "full": (FULL, COMMENTS, False),
    "full_owner_only": (FULL, COMMENTS, True),
    "bare": (BARE, [], False),
    "bare_with_comments": (BARE, COMMENTS, False),
}


def beads(name: str) -> tuple[Bead, list[Comment], bool]:
    bead, comments, owner_only = CASES[name]
    return bead_of(bead), [Comment(author=c["author"], text=c["text"]) for c in comments], owner_only
