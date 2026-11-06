"""Turn a failed bd call into a typed BdError. bd has no error codes beyond 13, so the words are all there is; the
words below are pinned by tests/test_classify.py against recorded bd 1.3.1 output."""

from __future__ import annotations

import json
import re

from beads_client.errors import BdError, ErrorKind
from beads_client.runner import EXIT_MISSING, EXIT_PRECONDITION, EXIT_TIMEOUT, BdRun

LINT_MISSING = re.compile(r"missing required sections?[^:\n]*:\s*(.+)", re.IGNORECASE)
# bd 1.3.1 exits 0 on a push the remote rejected; its words are git's
PUSH_REJECTED = re.compile(r"Updates were rejected|failed to push some refs|tip of your current branch is behind", re.IGNORECASE)
# Lock refusals, from the strings compiled into bd 1.3.1 ("embeddeddolt: acquiring lock: %w", "failed to acquire %s lock: %v",
# "Processes %s (bd/dolt) may be holding the lock."). Not yet captured from a live contention: pinned by tests as strings.
LOCKED = re.compile(r"acquiring lock|failed to acquire .*lock|may be holding the lock", re.IGNORECASE)


def loads(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return None


def error_of(run: BdRun) -> BdError:
    if run.code in (EXIT_MISSING, EXIT_TIMEOUT):
        return BdError("missing_binary" if run.code == EXIT_MISSING else "timeout", run.err.strip()[:500])
    said = loads(run.out)
    asked = said.get("error") if isinstance(said, dict) else None
    text = f"{run.err}\n{asked if isinstance(asked, str) else run.out}".strip()[:500]
    # unclaim reports a stale fence with exit 1, not 13
    if run.code == EXIT_PRECONDITION or "assignee mismatch" in text.lower() or "status mismatch" in text.lower():
        return BdError("precondition", text)
    lint = LINT_MISSING.search(text)
    if lint:
        sections = tuple(h.strip() for h in re.findall(r"##\s*([^,#(\n]+)", text[lint.start() :]))
        return BdError("lint", text, sections)
    low = text.lower()
    kind: ErrorKind = (
        "not_claimable"
        if any(w in low for w in ("not claimable", "already claimed", "claimed by a different actor"))
        else "not_found"
        if "not found" in low or "no issue" in low
        else "other"
    )
    return BdError(kind, text)
