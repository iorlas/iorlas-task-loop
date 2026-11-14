"""Explicit positive plan artifacts for lifecycle tests; invalid artifacts stay literal in their tests."""

READ_LIST = "## Read list\n- `src/a.py:1-2` — integration point.\n"
PLAN_TEXT = "# Plan\n\n" + READ_LIST
PLAN_V2 = "# Plan v2\n\n" + READ_LIST
