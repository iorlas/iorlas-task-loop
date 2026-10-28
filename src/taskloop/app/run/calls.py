"""Calls: the worker calls of a run. A call opens with its start record and closes with the end record and one row of the run's
sessions (the trace's `sessions`), so a reflection and the report read what the dashboard drew."""

import time
from collections.abc import Callable
from typing import Any

from taskloop.contracts.delegate import DelegateResult, LiveStart, WorkerStarted
from taskloop.contracts.log import CallEnd, CallStart
from taskloop.contracts.trace import Tokens
from taskloop.stores.runlog import RunLog

KEYS = ("in", "cached", "out")


def timing(obs: dict[str, Any]) -> dict[str, Any]:
    """The process boundaries of a call as the log records them: started, ended, first provider error, last output, kill."""
    return {k: obs.get(k) for k in ("started_t", "ended_t", "first_error_t", "last_event_t", "kill_t")}


class Calls:
    def __init__(
        self,
        log: RunLog,
        node_id: Callable[[], int | None],
        sessions: list[dict[str, Any]],
        stats: dict[str, int],
        opencode: Callable[[str], str],
        context_tokens: Callable[[str], int | None],
    ) -> None:
        self.log, self.node_id, self.sessions, self.stats = log, node_id, sessions, stats
        self.opencode, self.context_tokens = opencode, context_tokens  # a ref -> OpenCode's session id ('' if none); a transcript -> tokens

    def start(self, step: str, node: str, role: str, resume: bool, n: int) -> str:
        """The call is about to be made: its id, which the end record carries."""
        cid = self.log.next_id("c")
        nid = self.node_id()
        self.log.emit(CallStart(id=cid, n=n, step=step, node="n%d" % nid if nid else "", role=role, resume=resume))
        return cid

    def end(
        self,
        cid: str,
        node: str,
        role: str,
        tries: int,
        res: DelegateResult,
        stopped: str = "",
        resume: bool = False,
        prompt_chars: int | None = None,
        worker: WorkerStarted | None = None,
        live: LiveStart | None = None,
    ) -> dict[str, Any]:
        """The call ended (done or stopped): its record, its session row, the run's token counts. A call that stopped before it named its
        thread or model still names them from the live file: `worker` (the first line) and `live` (the `start` event)."""
        st = res.stop
        ref = res.ref or (worker.run_id if worker else "")
        model, lane = res.model or (live.model if live else ""), res.lane or (live.lane if live else "")
        tk = res.tokens
        row: dict[str, Any] = {
            "node": node,
            "role": role,
            "attempt": tries,
            "status": "done" if st is None else "stopped",
            "ref": ref,
            "run_id": res.run_id or (worker.run_id if worker else None),
            "transcript": res.transcript or "",
            "family": res.family or "",
            "lane": lane,
            "model": model,
            "effort": res.effort or (live.effort if live else ""),
            "turns": res.usage.turns if res.usage else None,
            "secs": round(res.secs or 0),
            "cost": res.cost or 0.0,
            "t": time.time(),
            "stopped": stopped,
            "tokens": {"in": tk.in_, "cached": tk.cached, "out": tk.out} if tk else None,
            "denied": [{"kind": d.kind, "tool": d.tool, "path": d.path or "", "input": d.input} for d in res.denied],
            "reason": st.reason if st else None,
            "exit": res.exit_code,
            "stop": {"scope": st.scope, "permanence": st.permanence, "retry": st.retry.kind} if st else None,
            "warning": res.warning or None,
            "context": res.context,
            "node_id": self.node_id(),
            "resume": resume,
            "flag": res.flag,
            "prompt_chars": prompt_chars,
        }
        if node == "write":  # where the session's context stands now: what the next round weighs against write_fresh_above_k
            if not row["transcript"] and self.opencode(row["ref"]):  # OpenCode: the session id stands for the transcript
                row["transcript"] = "opencode:" + self.opencode(row["ref"])
            tok = self.context_tokens(row["transcript"])
            row["context_k"] = round(tok / 1000) if tok else None
        for k in KEYS:
            self.stats["tokens_" + k] += int((row["tokens"] or {}).get(k) or 0)
        self.sessions.append(row)
        tk = row["tokens"] or {}
        self.log.emit(
            CallEnd(
                id=cid,
                status=row["status"],
                reason=row["reason"],
                ref=row["ref"] or "",
                lane=row["lane"] or "",
                model=row["model"] or "",
                effort=row["effort"],
                secs=float(row["secs"]),
                cost=float(row["cost"]),
                tokens=Tokens(in_=int(tk.get("in") or 0), cached=int(tk.get("cached") or 0), out=int(tk.get("out") or 0)),
                family=row["family"] or "",
                flag=row["flag"],
                transcript=row["transcript"],
                exit=res.exit_code,
            )
        )
        return row
