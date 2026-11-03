"""Beads ID conventions: prefixes and references in tracker prose stay at the adapter boundary."""
import re


def prefix_of(task_id: str | None) -> str:
    """The tracker namespace used by artifact lookup and report filters."""
    return (task_id or "").split("-", maxsplit=1)[0]


def mentioned_ids(task_id: str, text: str) -> list[str]:
    """IDs in the same tracker namespace named in prose, in order, once each."""
    prefix = prefix_of(task_id)
    found = re.findall(rf"(?<![\w.-])({re.escape(prefix)}-[A-Za-z0-9]+(?:\.[0-9]+)*)", text)
    return list(dict.fromkeys(found))
