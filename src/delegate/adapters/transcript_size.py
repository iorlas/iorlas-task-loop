"""How big a worker's context was at its last turn, read from its transcript (Claude and Codex JSONL). The call's own `tokens` add up
every turn, so they say nothing of the size; the last turn does."""

import json
from pathlib import Path


def last_turn_tokens(line: str) -> int | None:
    """The input tokens (cache included) a transcript line reports, None when it reports none."""
    try:
        rec = json.loads(line)
        if rec.get("type") == "assistant" and not rec.get("isSidechain"):
            u = rec["message"]["usage"]
            return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if (rec.get("payload") or {}).get("type") == "token_count":
            return int(rec["payload"]["info"]["last_token_usage"]["input_tokens"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def context_k(path: str | Path | None, tail: int = 1 << 20) -> float | None:
    """The size in thousands of tokens of the last turn in a transcript, or None (no file, no usage line)."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return None
    for line in reversed(lines):
        if '"usage"' not in line and '"token_count"' not in line:
            continue
        tokens = last_turn_tokens(line)
        if tokens is not None:
            return round(tokens / 1000, 1)
    return None
