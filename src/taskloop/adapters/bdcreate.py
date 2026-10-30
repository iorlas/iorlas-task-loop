"""bd create that is known to have worked: bd's lint refuses a body that lacks sections (Touches, Acceptance Criteria);
they are added once."""
import re
from collections.abc import Callable

from taskloop.contracts.ports import BdFailure, Beads, NewBead

LINT_FILLER = {
    "acceptance criteria": "- The follow-up named in the title is done, and the checks of the code it touches pass.",
    "touches": "Not known yet: the writer who picks this up names the files it changes (found while working on %(bead)s).",
    "steps to reproduce": "See the description above (found while working on %(bead)s); the reproduction is not recorded.",
}


def with_sections(body: str, headings: list[str], bead: str) -> str:
    """The description with each missing section appended (a filler that says so, never an invented fact)."""
    have = {h.lower() for h in re.findall(r"^##\s*(.+?)\s*$", body or "", re.M)}
    add = [f"## {h}\n" + LINT_FILLER.get(h.lower(), "(not recorded: found while working on %(bead)s)") % {"bead": bead}
           for h in headings if h.lower() not in have]
    return (body or "").rstrip() + ("\n\n" + "\n\n".join(add) if add else "")


def create_checked(store: Beads, new: NewBead, bead: str, note: Callable[[str], object]) -> tuple[str, str]:
    """-> (the new id, "") or ("", why not): nothing was created then (tl-7y6.7.9: 98 follow-ups were called filed and none existed).
    When bd refuses the body for missing sections, they are added and it is tried once more."""
    try:
        return store.create(new), ""
    except BdFailure as e:
        need = e.error.missing_sections
        if not need or not new.description:
            return "", e.error.text
    note(f"bd refused the create ({', '.join(need)}): trying again with the sections it names")
    try:
        return store.create(new.replace(description=with_sections(new.description, need, bead))), ""
    except BdFailure as e:
        return "", e.error.text
