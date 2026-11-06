"""Which task-loop versions are running where: a loop engine on a version other than the newest installed is skew."""
from collections.abc import Sequence


def skew(loops: Sequence[str], installed: str) -> list[str]:
    """The distinct loop versions that are not the newest installed one, in order of first appearance; [] when none is installed."""
    if not installed:
        return []
    seen: list[str] = []
    for v in loops:
        if v and v != installed and v not in seen:
            seen.append(v)
    return seen
