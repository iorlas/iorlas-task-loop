"""bd's JSON (1.3.1) as typed records. Reads are tolerant: bd adds keys, and a key we do not model is dropped,
never an error. Metadata keys with a typed home move there; the rest stay in `BeadMeta.extra`."""
import re
from typing import Any

from taskloop.contracts.bead import BdError, Bead, BeadMeta, Comment, SlotHold

LINT_MISSING = re.compile(r"missing required sections?[^:\n]*:\s*(.+)", re.I)
_TYPED_META = ("held_bead", "slot_hold")


def _str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) else ""


def meta_of(raw: Any) -> BeadMeta:
    if not isinstance(raw, dict):
        return BeadMeta()
    hold = raw.get("slot_hold")
    slot_hold = None
    if isinstance(hold, dict):
        until = hold.get("until")
        slot_hold = SlotHold(until=float(until) if isinstance(until, (int, float)) else None, why=_str(hold, "why"))
    return BeadMeta(held_bead=_str(raw, "held_bead"), slot_hold=slot_hold,
                    extra={k: v for k, v in raw.items() if k not in _TYPED_META})


def dep_ids(raw: Any) -> list[str]:
    out = [d.get("depends_on_id") for d in raw if isinstance(d, dict) and d.get("type") != "parent-child"] if isinstance(raw, list) else []
    return [x for x in out if isinstance(x, str)]


def bead_of(d: dict[str, Any]) -> Bead:
    prio = d.get("priority")
    labels = d.get("labels")
    return Bead(id=str(d["id"]), title=_str(d, "title"), status=_str(d, "status"), issue_type=_str(d, "issue_type"),
                priority=prio if isinstance(prio, int) else None, assignee=_str(d, "assignee"),
                labels=sorted(x for x in labels if isinstance(x, str)) if isinstance(labels, list) else [],
                parent=_str(d, "parent"), description=_str(d, "description"), design=_str(d, "design"),
                acceptance_criteria=_str(d, "acceptance_criteria"), notes=_str(d, "notes"),
                dependencies=dep_ids(d.get("dependencies")), metadata=meta_of(d.get("metadata")),
                lease_expires_at=_str(d, "lease_expires_at"))


def beads_of(data: Any) -> list[Bead]:
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) and "id" in data else []
    return [bead_of(r) for r in rows if isinstance(r, dict) and "id" in r]


def comments_of(data: Any) -> list[Comment]:
    rows = data if isinstance(data, list) else []
    return [Comment(author=_str(r, "author"), text=_str(r, "text"), created_at=_str(r, "created_at"))
            for r in rows if isinstance(r, dict)]


def error_of(stderr: str, stdout: str) -> BdError:
    """Classify a failed bd call from its output (bd has no error codes: the words are all there is)."""
    text = "%s\n%s" % (stderr, stdout)
    lint = LINT_MISSING.search(text)
    if lint:
        return BdError(kind="lint", missing_sections=[h.strip() for h in re.findall(r"##\s*([^,#\n]+)", lint.group(1))],
                       text=text.strip()[:500])
    low = text.lower()
    kind = ("not_claimable" if "not claimable" in low or "already claimed" in low else
            "not_found" if "not found" in low or "no issue" in low else "other")
    return BdError(kind=kind, text=text.strip()[:500])
