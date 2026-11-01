"""Answers a run already took, indexed by call coordinates and semantic execution digest.

Legacy prompt-only hashes cannot match the versioned execution identity; their output stays on disk for inspection.
"""

import json
from pathlib import Path
from typing import Any

from taskloop.app.run import worker_identity
from taskloop.contracts.guard import guard
from taskloop.contracts.paths import RunFiles
from taskloop.contracts.run import CallIdentity, DoneEntry, DoneMemo
from taskloop.contracts.stores import JsonStore


def _store(run_dir: Path) -> JsonStore[DoneMemo]:
    return JsonStore(RunFiles(run_dir).done_memo(), DoneMemo)


def recall(
    run_dir: Path, key: tuple[Any, ...], sha: str, identity: CallIdentity | None = None,
) -> dict[str, Any] | None:
    """Reuse consumed work against its admitted inputs, before later engine effects."""
    memo = _store(run_dir).get()
    entry = memo.done.get(json.dumps(list(key))) if memo else None
    if entry is None:
        return None
    if entry.identity is not None and identity is not None:
        before = entry.identity
        if (before.semantics, before.worktree, before.cwd) != (identity.semantics, identity.worktree, identity.cwd):
            return None
        # A consumed step belongs to these coordinates in this run. Its worker,
        # checks and WIP save may have changed the checkout since admission.
        sha = worker_identity.execution_id(before)
    if entry.sha != sha:
        return None
    try:
        raw = json.loads(Path(entry.file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def keep(
    run_dir: Path, key: tuple[Any, ...], sha: str, answer_file: str, identity: CallIdentity | None = None,
) -> None:
    """The answer of the call at `key` was valid and used: remember where its raw copy is."""
    if not answer_file:
        return
    store = _store(run_dir)
    try:
        with guard(store.path.with_name(store.path.name + ".lock")):  # read, add, write as one step
            memo = store.get() or DoneMemo()
            entry = DoneEntry(sha=sha, file=answer_file, identity=identity)
            store.write(memo.replace(done={**memo.done, json.dumps(list(key)): entry}))
    except OSError:
        pass
