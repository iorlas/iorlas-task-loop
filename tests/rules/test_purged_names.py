"""LANEPURGE rule (tl-w7lt.38.11): the word "lane" is gone from src, packages, skills, tests, dev and docs. It had three meanings and
each has a name now (account, track, loop); the dashboard's Floor tab is Slots. A new use fails here unless its file is named below with
the reason.
Matched: lane/lanes/LANE/LANES as a word or identifier part (first_lane, LaneCard, no_lane); not words that merely contain it (plane, or
the name LANEPURGE)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("src", "packages", "skills", "tests", "dev", "docs", "README.md", "CLAUDE.md", "AGENTS.md")
WORD = re.compile(r"(?<![A-Za-z])(?:[Ll]anes?|LANES?)(?![A-Za-z])|[a-z]Lane(?![A-Za-z])|(?<![A-Za-z])Lane[A-Z]")
SKIPPED_PARTS = frozenset({"__pycache__", ".venv", ".task", "node_modules"})

# Trees that are not edited: vendored code (its hash is guarded by VendorGuard) and the history written before the purge.
EXCLUDED_TREES = {
    "skills/task-loop/_vendor": "vendored shelf code; never renamed (tests/rules VendorGuard holds its hash)",
    "docs/architecture": "history: architecture notes and reviews written before the purge",
    "docs/review": "history: reviews written before the purge",
}
# Files that describe the purge itself and so must name the old word.
PURGE_RECORDS = {
    "tests/rules/test_purged_names.py": "this rule names the word it forbids",
    "docs/design/naming-audit.md": "the audit that fixed the three meanings and their new names",
    "docs/design/lanepurge.md": "the file count and the cut order of the purge",
    "docs/glossary.md": "the lane row and the avoid-lists name the purged word as the word not to use",
}
# The bead label prefix is a value the repo chooses (`area_label_prefix`, default "lane:"); only `lane:` occurrences are allowed in these.
LABEL_PREFIX = {
    "dev/race.py": "the race simulation sets area_label_prefix and labels beads lane:a",
    "skills/task-loop/SKILL.md": "documents the lane: label prefix of areas",
    "packages/areas/src/tlareas/policy.py": "the area policy docstring quotes lane:live",
    "packages/areas/src/tlareas/testing.py": "the fake sets the prefix and a lane:live label",
    "packages/areas/tests/test_admission.py": "area tests use lane: labels",
    "packages/areas/tests/test_policy.py": "area tests use lane: labels",
    "tests/asks/test_engine_asks.py": "an ask test labels a bead lane:",
    "tests/land/test_race_invariants.py": "the race invariants label beads lane:",
    "tests/plan/test_engine_plan.py": "a plan test labels a bead lane:",
    "tests/slots/real/test_areas.py": "area tests use lane: labels",
    "tests/slots/test_areas.py": "area tests use lane: labels",
    "packages/work/tests/fixtures/briefs": "captured briefs of real runs quote the lane: label prefix",
}
# The vendored any_agent keeps its own class name; the one test that imports it says so.
VENDORED_SYMBOL = {
    "packages/delegate/tests/real/test_run_stops_real.py": ("LaneGoneWatcher", "imports the vendored any_agent LaneGoneWatcher"),
}


def under(rel: str, tree: str) -> bool:
    return rel == tree or rel.startswith(tree + "/")


def files() -> list[str]:
    found = []
    for name in SCANNED:
        base = ROOT / name
        for path in ([base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and not SKIPPED_PARTS & set(path.parts) and not any(under(rel, t) for t in EXCLUDED_TREES):
                found.append(rel)
    return found


def stray(rel: str, text: str) -> list[str]:
    """The matches of one file that its allowance (if any) does not cover, as 'line: text'."""
    if rel in PURGE_RECORDS:
        return []
    prefix = any(under(rel, f) for f in LABEL_PREFIX)
    symbol = VENDORED_SYMBOL.get(rel, ("", ""))[0]
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in WORD.finditer(line):
            if prefix and line.startswith(":", m.end()):
                continue
            if symbol and line[m.start():m.end() + len(symbol)].startswith(symbol):
                continue
            out.append(f"{n}: {line.strip()[:120]}")
    return out


def test_the_word_lane_appears_only_where_it_is_named():
    bad = []
    for rel in files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        bad += [f"{rel}:{hit}" for hit in stray(rel, text)]
    why = "the word lane is purged (account, track, loop; Slots); name the file in tests/rules/test_purged_names.py with a reason:\n"
    assert not bad, why + "\n".join(bad[:40])


def test_every_allowance_names_a_file_that_still_needs_it():
    stale = [name for name in (*PURGE_RECORDS, *LABEL_PREFIX, *VENDORED_SYMBOL)
             if not (ROOT / name).exists()]
    assert not stale, f"allowances for files that do not exist: {stale}"
