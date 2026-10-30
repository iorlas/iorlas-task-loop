"""The answers a run already took, kept in the run dir: a run that paused for the network, or moved to a newer install, goes on from its
checkpoint, which can sit before steps that were finished, and their output is kept (`recall`) instead of asked for again."""

import json
from pathlib import Path
from typing import Any

from taskloop.contracts.guard import guard
from taskloop.contracts.paths import RunFiles
from taskloop.contracts.run import DoneEntry, DoneMemo
from taskloop.contracts.stores import JsonStore


def _store(run_dir: Path) -> JsonStore[DoneMemo]:
    return JsonStore(RunFiles(run_dir).done_memo(), DoneMemo)


def recall(run_dir: Path, key: tuple[Any, ...], sha: str) -> dict[str, Any] | None:
    """The raw answer this run already took for the call at `key` (same place, same prompt `sha`), or None."""
    memo = _store(run_dir).get()
    entry = memo.done.get(json.dumps(list(key))) if memo else None
    if entry is None or entry.sha != sha:
        return None
    try:
        raw = json.loads(Path(entry.file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def keep(run_dir: Path, key: tuple[Any, ...], sha: str, answer_file: str) -> None:
    """The answer of the call at `key` was valid and used: remember where its raw copy is."""
    if not answer_file:
        return
    store = _store(run_dir)
    try:
        with guard(store.path.with_name(store.path.name + ".lock")):  # read, add, write as one step
            memo = store.get() or DoneMemo()
            store.write(memo.replace(done={**memo.done, json.dumps(list(key)): DoneEntry(sha=sha, file=answer_file)}))
    except OSError:
        pass
