"""How big a worker's context was at its last turn, read from its transcript."""
import json
from typing import Any

from taskloop.adapters import opencode


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


def context_tokens(path: Any, tail: int = 1 << 20) -> int | None:
    """-> the input tokens (cache included) of the last turn in a worker's transcript, or None: Claude's last assistant message
    usage, Codex's last token_count, OpenCode's last assistant message tokens (`opencode:ses_...`, read from its DB). The
    answer's own `tokens` add up every turn of the call, so they say nothing of the size."""
    session = opencode.opencode_id(path)
    if session:
        return opencode.opencode_context(session)
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
            return tokens
    return None
