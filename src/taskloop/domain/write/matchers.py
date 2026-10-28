"""Policy over the task's diff: how many tests it adds and removes (tests/write/test_matchers.py)."""
import re

GHERKIN_TEST = re.compile(r"^\s*Scenario( Outline)?:")  # a use-case scenario (Reqnroll, lifesim-fld.26.10)


def count_tests(diff: str, pattern: str) -> tuple[int, int]:
    """(added, removed): lines of a unified diff matching the repo's test pattern (engine.test_pattern), and Gherkin scenarios in
    .feature files."""
    rx, feature = re.compile(pattern), False
    added = removed = 0
    for ln in diff.splitlines():
        if ln.startswith(("+++", "---")):
            if not ln.rstrip().endswith("/dev/null"):  # a deleted file names itself on its --- line only
                feature = ln.rstrip().endswith(".feature")
            continue
        hit = (GHERKIN_TEST if feature else rx).search(ln[1:])
        if ln.startswith("+") and hit:
            added += 1
        elif ln.startswith("-") and hit:
            removed += 1
    return added, removed
