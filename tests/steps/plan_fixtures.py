"""Explicit positive plan artifacts for lifecycle tests; invalid artifacts stay literal in their tests."""

HEADER = "# Header\nTask: tl-1\nBase: source\nDepth: small; one behaviour.\n"
CHANGE_MAP = "## Change map\n- `src/a.py` — `integrate`: integration point.\n"
PLAN_TEXT = HEADER + "\n" + CHANGE_MAP
PLAN_V2 = HEADER + "\nOutcome: revised.\n" + CHANGE_MAP
