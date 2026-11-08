"""Code overlap and display claims: docs/design/merge-queue.md section 11, edge case 4."""
from collections.abc import Collection, Mapping, Sequence


def overlaps(a: Collection[str], b: Collection[str]) -> bool:
    """Match equal paths or directory ancestors, respecting path boundaries."""
    return any(
        left.rstrip("/") == right.rstrip("/")
        or left.startswith(right.rstrip("/") + "/")
        or right.startswith(left.rstrip("/") + "/")
        for left in a for right in b
    )


def waits_for(
    order: Sequence[str],
    touched: Mapping[str, Collection[str]],
    conflicts: Collection[frozenset[str]] = frozenset(),
) -> dict[str, str]:
    """Name the nearest earlier overlapping PR; caller supplies textual conflicts."""
    waiting: dict[str, str] = {}
    for index, pr in enumerate(order):
        for earlier in reversed(order[:index]):
            if frozenset((pr, earlier)) in conflicts or overlaps(
                touched.get(pr, ()), touched.get(earlier, ()),
            ):
                waiting[pr] = earlier
                break
    return waiting


def claims(touches_text: str) -> list[str]:
    """Read paths from the Touches section for display, never dispatch gating."""
    paths: list[str] = []
    in_section = False
    for line in touches_text.splitlines():
        text = line.strip()
        if text.startswith("#"):
            if in_section and (text.startswith("## ") or text.startswith("# ")):
                break
            if text == "## Touches":
                in_section = True
        elif in_section and text.startswith(("- ", "• ")):
            path = text[2:].strip().strip("`")
            if path:
                paths.append(path)
    return paths
