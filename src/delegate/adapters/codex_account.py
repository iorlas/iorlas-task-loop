"""What the Codex CLI keeps outside a run: the rate limits (`codex app-server`, one JSON-RPC exchange) and the rollout files under
$CODEX_HOME/sessions (token totals of a thread, of its child threads, and its context size). Undocumented layouts: this is the one
reader."""

import contextlib
import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import IO

from delegate.adapters import procs
from delegate.contracts.json_types import Json

APP_SERVER_S = 8  # seconds each codex app-server reply may take


def sessions_root():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def _send(stdin: IO[bytes], m: dict[str, Json]) -> None:
    stdin.write((json.dumps(m) + "\n").encode())
    stdin.flush()


def _read(stdout: IO[bytes], pending: bytearray, i: int, seconds: float) -> dict[str, Json] | None:
    """The reply with id `i`, else None at the deadline or EOF: the wait itself is bounded (select), not only the gaps between lines."""
    end = time.monotonic() + seconds
    fd = stdout.fileno()
    while True:
        while b"\n" in pending:
            line, _, rest = bytes(pending).partition(b"\n")
            pending[:] = rest
            with contextlib.suppress(ValueError):
                m = json.loads(line)
                if isinstance(m, dict) and m.get("id") == i:
                    return m
        left = end - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            return None
        chunk = os.read(fd, 65536)
        if not chunk:
            return None
        pending.extend(chunk)


def _failure(r: dict[str, Json] | None) -> str:
    """The server's own error text for a reply with no result, else the generic one."""
    err = (r or {}).get("error")
    msg = err.get("message") if isinstance(err, dict) else None
    return msg if isinstance(msg, str) and msg else "codex gave no limits (logged in? run `codex login`)"


def rate_limits() -> tuple[dict[str, Json] | None, str | None]:
    """-> (result_dict, error_text). Spawns `codex app-server` once; ~1-2 s."""
    exe = shutil.which("codex")
    if not exe:
        return None, "codex CLI not installed"
    try:
        p, _ = procs.spawn([exe, "app-server"], stderr=subprocess.DEVNULL, session=False)
    except OSError as e:
        return None, f"codex app-server failed to start: {e}"
    stdin, stdout = p.stdin, p.stdout
    assert stdin is not None and stdout is not None  # both are PIPEs
    pending = bytearray()
    try:
        init: dict[str, Json] = {
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "delegate-route", "title": "delegate route", "version": "1"}},
        }
        _send(stdin, init)
        if _read(stdout, pending, 1, APP_SERVER_S) is None:
            return None, "codex app-server did not answer"
        _send(stdin, {"method": "initialized"})
        _send(stdin, {"id": 2, "method": "account/rateLimits/read"})
        r = _read(stdout, pending, 2, APP_SERVER_S)
    except BrokenPipeError:  # the server exited under us
        return None, "codex app-server closed its input"
    finally:
        procs.kill_tree(p)
        p.wait()
        for f in (stdin, stdout):
            with contextlib.suppress(OSError):
                f.close()
    result = (r or {}).get("result")
    if not isinstance(result, dict):
        return None, _failure(r)
    return result, None


def child_tokens(thread: str, since: float):
    """-> (tokens, threads) the child threads of a codex thread spent since `since`: the automatic reviewer runs as one, in its own
    rollout file under $CODEX_HOME/sessions/Y/M/D (local date), and `codex exec --json` never reports it. Each file's last token_count
    holds its total."""
    tot, n = {"in": 0, "cached": 0, "out": 0}, 0
    root = sessions_root()
    for day in sorted({time.strftime("%Y/%m/%d", time.localtime(x)) for x in (since, time.time())}):
        for f in (root / day).glob("rollout-*.jsonl"):
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
                if f.stat().st_mtime < since:
                    continue
                with f.open(encoding="utf-8", errors="replace") as fh:
                    if (json.loads(fh.readline()).get("payload") or {}).get("parent_thread_id") != thread:
                        continue
                    last = None
                    for line in fh:
                        if '"token_count"' in line:
                            last = line
                if last:
                    u = json.loads(last)["payload"]["info"]["total_token_usage"]
                    tot = {
                        "in": tot["in"] + (u.get("input_tokens") or 0),
                        "cached": tot["cached"] + (u.get("cached_input_tokens") or 0),
                        "out": tot["out"] + (u.get("output_tokens") or 0),
                    }
                    n += 1
    return tot, n


def thread_total(thread: str):
    """-> {in, cached, out} a codex thread has spent so far, or None: its rollout file (any day) ends with a token_count holding the
    thread's total. `turn.completed` on `exec resume` reports that running total too, so a resumed run subtracts what came before."""
    root = sessions_root()
    for f in root.glob(f"*/*/*/rollout-*{thread}.jsonl"):
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
            last = None
            with f.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"token_count"' in line:
                        last = line
            if last:
                u = json.loads(last)["payload"]["info"]["total_token_usage"]
                return {"in": u.get("input_tokens") or 0, "cached": u.get("cached_input_tokens") or 0, "out": u.get("output_tokens") or 0}
    return None


def context_k(thread: str | None):
    """-> thousands of input tokens of the thread's last model request (its context size), from the end of its rollout file, else None."""
    if not thread:
        return None
    root = sessions_root()
    for f in root.glob(f"*/*/*/rollout-*{thread}.jsonl"):
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
            with f.open("rb") as fh:
                fh.seek(max(0, f.stat().st_size - 131072))
                tail = fh.read().decode("utf-8", "replace").splitlines()
            for line in reversed(tail):
                if '"token_count"' in line:
                    info = json.loads(line)["payload"]["info"]
                    return round(info["last_token_usage"]["input_tokens"] / 1000, 1)
    return None
