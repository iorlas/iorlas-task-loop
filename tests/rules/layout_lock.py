"""Layout lock against the merge base with origin/main, with no stored snapshot.

A node is an app slice, taskloop layer, dashboard, delegate, package, or individual
module directly under taskloop or app. Adding, editing or deleting a module inside
an existing node and in-node renames are free (removing the whole node is not).
Git -M60% detects moves at >=60% similarity; a move disguised as a rewrite below
that threshold counts as deletion plus addition of unrelated files and stays free.
"""
import configparser
import re
from pathlib import Path, PurePosixPath

from rules.ratchet_change import MIN_REASON_WORDS, git, merge_base

ENABLED = True
MOVE_SIMILARITY = "60%"
"""A move detected by git at >=60% similarity; a move disguised as a rewrite below
it counts as delete plus add of unrelated files and stays free."""
ALLOW = re.compile(r"^Layout-allow:[ \t]+(node|move|contract)[ \t]+([^\n]+)$", re.MULTILINE)


def node_of(path: str) -> str | None:  # noqa: PLR0911  one return per kind of node
    parts = PurePosixPath(path).parts
    if not path.endswith(".py"):
        return None
    if len(parts) >= 4 and parts[0] == "packages" and parts[2] == "src":
        return f"packages/{parts[1]}"
    if len(parts) >= 3 and parts[:2] in (("src", "delegate"),):
        return parts[1]
    if len(parts) < 3 or parts[:2] != ("src", "taskloop"):
        return None
    if len(parts) == 3:
        return f"taskloop:{parts[-1]}"
    if parts[2] == "app":
        return f"app:{parts[-1]}" if len(parts) == 4 else f"app/{parts[3]}"
    return parts[2]


def name_status(root: Path, base: str) -> list[tuple[str, str, str]]:
    """Python changes, including untracked adds; absent endpoints are empty strings."""
    entries = []
    for line in git(root, "diff", "--name-status", f"-M{MOVE_SIMILARITY}", base).stdout.splitlines():
        status, *paths = line.split("\t")
        old = paths[0] if status[0] != "A" else ""
        new = paths[-1] if status[0] != "D" else ""
        if old.endswith(".py") or new.endswith(".py"):
            entries.append((status, old, new))
    tracked_adds = {new for _, _, new in entries}
    for path in git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines():
        if path.endswith(".py") and path not in tracked_adds:
            entries.append(("A", "", path))
    return entries


def classify_files(entries: list[tuple[str, str, str]], existing_nodes: dict[str, str]) -> dict[str, list[str]]:
    """Classify changes using the merge base's file-to-node mapping."""
    found: dict[str, list[str]] = {}
    before = set(existing_nodes.values())
    after = dict(existing_nodes)
    for status, old, new in entries:
        if status.startswith(("D", "R")):
            after.pop(old, None)
        node = node_of(new)
        if node is not None and not status.startswith("D"):
            after[new] = node
        if status.startswith("A") and node is not None and node not in before:
            found.setdefault("node", []).append(f"new node {node}: {new}")
        if status.startswith("R") and node_of(old) != node:
            found.setdefault("move", []).append(f"{old} -> {new}")
    for node in sorted(before - set(after.values())):
        found.setdefault("node", []).append(f"removed node {node}")
    return found


def parse_contracts(text: str) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return {section: dict(parser[section]) for section in parser.sections() if section.startswith("importlinter:contract:")}


def lines(value: str) -> set[str]:
    return {line.strip() for line in value.splitlines() if line.strip()}


def contract_loosening(old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]) -> list[str]:
    found = []
    for section, options in old.items():
        if section not in new:
            found.append(f"removed contract {section}")
            continue
        now = new[section]
        for option in ("source_modules", "forbidden_modules", "layers", "containers"):
            if lines(options.get(option, "")) - lines(now.get(option, "")):
                found.append(f"{section}: removed {option} lines")
    for section, now in new.items():
        if section not in old:
            continue
        options = old[section]
        if lines(now.get("ignore_imports", "")) - lines(options.get("ignore_imports", "")):
            found.append(f"{section}: added ignore_imports lines")
        if now.get("allow_indirect_imports", "").lower() == "true" and options.get("allow_indirect_imports", "").lower() != "true":
            found.append(f"{section}: enabled allow_indirect_imports")
    return found


def rule_changes(paths: list[str], old_conftest: str = "", new_conftest: str = "") -> list[str]:
    """Protected rule edits, and changes specifically to the LIMITS_S line."""
    found = [path for path in paths if path == "tests/rules/gate_rules.py" or
             (path.startswith("tests/rules/") and "ratchet" in PurePosixPath(path).name and path.endswith(".py"))]
    if "tests/conftest.py" in paths:
        old = [line for line in old_conftest.splitlines() if re.match(r"^LIMITS_S\b", line)]
        new = [line for line in new_conftest.splitlines() if re.match(r"^LIMITS_S\b", line)]
        if old != new:
            found.append("tests/conftest.py: LIMITS_S changed")
    return found


def allowed_kinds(log: str) -> set[str]:
    return {kind for kind, reason in ALLOW.findall(log) if len(reason.split()) >= MIN_REASON_WORDS}


def problems(root: Path) -> list[str] | None:
    base = merge_base(root)
    if base is None:
        return None
    existing = {}
    for path in git(root, "ls-tree", "-r", "--name-only", base).stdout.splitlines():
        node = node_of(path)
        if node is not None:
            existing[path] = node
    entries = name_status(root, base)
    found = classify_files(entries, existing)

    def texts(path: str) -> tuple[str, str]:
        old = git(root, "show", f"{base}:{path}").stdout
        file = root / path
        return old, file.read_text(encoding="utf-8") if file.is_file() else ""

    old, new = texts(".importlinter")
    contracts = contract_loosening(parse_contracts(old), parse_contracts(new))
    paths = sorted({path for _, old, new in entries for path in (old, new) if path})
    contracts += rule_changes(paths, *texts("tests/conftest.py"))
    found["contract"] = contracts
    allowed = allowed_kinds(git(root, "log", "--format=%B", f"{base}..HEAD").stdout)
    return [f"{item}; add `Layout-allow: {kind} <reason in words>` to a commit"
            for kind, items in found.items() if kind not in allowed for item in items]
