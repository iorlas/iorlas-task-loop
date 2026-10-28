"""The answers a run already took, kept in the run dir: a run that paused for the network, or moved to a newer install, goes on from its
checkpoint, which can sit before steps that were finished, and their output is kept (`recall`) instead of asked for again."""

import json
from pathlib import Path
from typing import Any

FILE = "done.json"


def recall(run_dir: Path, key: tuple[Any, ...], sha: str) -> dict[str, Any] | None:
    """The raw answer this run already took for the call at `key` (same place, same prompt `sha`), or None."""
    try:
        entry = json.loads((run_dir / FILE).read_text(encoding="utf-8")).get(json.dumps(list(key)))
        if isinstance(entry, dict) and entry.get("sha") == sha:
            raw = json.loads(Path(entry["file"]).read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def keep(run_dir: Path, key: tuple[Any, ...], sha: str, answer_file: str) -> None:
    """The answer of the call at `key` was valid and used: remember where its raw copy is."""
    if not answer_file:
        return
    f = run_dir / FILE
    try:
        memo = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        memo[json.dumps(list(key))] = {"sha": sha, "file": answer_file}
        f.write_text(json.dumps(memo), encoding="utf-8")
    except (OSError, ValueError):
        pass
