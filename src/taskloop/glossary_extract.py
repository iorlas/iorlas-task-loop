"""Read term tables, retaining source definitions within a byte budget."""

import re

PATH = "docs/glossary.md"
MAX_BYTES = 128 * 1024
BUDGET = 2000
PRIORITY = ("task", "task tracker", "plan", "step", "attempt", "session", "slot", "land")
HEADING = "Partial glossary (term and meaning only):\n"
NOTE = f"\nOmitted terms: consult {PATH} only for missing terms.\n"


def cells(line: str) -> tuple[str, ...]:
    """Markdown pipes outside inline code, honoring escaped pipes and backtick runs."""
    parts: list[str] = []
    part = ""
    code = 0
    index = 0
    line = line.strip()
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            part += line[index:index + 2]
            index += 2
            continue
        if char == "`":
            end = index + 1
            while end < len(line) and line[end] == "`":
                end += 1
            width = end - index
            code = (0 if width == code else code) if code else width
            part += line[index:end]
            index = end
            continue
        if char == "|" and not code:
            parts.append(part.strip())
            part = ""
        else:
            part += char
        index += 1
    parts.append(part.strip())
    return tuple(parts[1:-1] if line.startswith("|") and line.endswith("|") else parts)


def rows(text: str) -> list[tuple[str, str, bool]]:
    """Validate every present term table; implementation details sort after core tables."""
    result: list[tuple[str, str, bool]] = []
    lines = text.splitlines()
    detail = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            detail = line == "## Factory vocabulary as built"
        header = cells(line)
        if header[:2] != ("Term", "Meaning"):
            index += 1
            continue
        index += 1
        separator = cells(lines[index]) if index < len(lines) else ()
        if len(separator) != len(header) or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            raise ValueError("Malformed glossary term table separator")
        index += 1
        count = 0
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            row = cells(lines[index])
            if len(row) != len(header) or not row[0] or not row[1]:
                raise ValueError("Malformed glossary term table row")
            result.append((row[0], row[1], detail))
            count += 1
            index += 1
        if not count:
            raise ValueError("Empty glossary term table")
    if not result:
        raise ValueError("No glossary term tables")
    return result


def extract(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError(f"{PATH} exceeds {MAX_BYTES} bytes")
    found = rows(data.decode("utf-8"))
    ordered = sorted(found, key=lambda row: (0, PRIORITY.index(row[0])) if row[0] in PRIORITY else (1 + row[2], 0))
    text = HEADING
    for term, meaning, _detail in ordered:
        row = f"{term}: {meaning}\n"
        if len((text + row + NOTE).encode("utf-8")) <= BUDGET:
            text += row
    if text == HEADING:
        raise ValueError("No complete glossary definition fits the extract")
    return text + NOTE
