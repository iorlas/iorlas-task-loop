"""Calls: the worker calls of a run. A call opens with its start record and closes with the end record and one row of the run's
sessions (the trace's `sessions`), so a reflection and the report read what the dashboard drew."""

import time
from collections.abc import Callable
from typing import Any

from tlkernel.delegate import DelegateResult, LiveStart, WorkerStarted
from tlkernel.log import CallEnd, CallStart, CallTokens

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
    ) -> None:
        self.log, self.node_id, self.sessions, self.stats = log, node_id, sessions, stats

    def start(self, step: str, node: str, role: str, resume: bool, n: int) -> str:
        """The call is about to be made: its id, which the end record carries."""
        cid = self.log.next_id("c")
        nid = self.node_id()
        self.log.emit(CallStart(id=cid, n=n, step=step, node=f"n{nid}" if nid else "", role=role, resume=resume))
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
        model, account = res.model or (live.model if live else ""), res.account or (live.account if live else "")
        tk = res.tokens
        row: dict[str, Any] = {
            "node": node,
            "role": role,
            "attempt": tries,
            "status": "done" if st is None else "stopped",
            "ref": ref,
            "run_id": res.run_id or (worker.run_id if worker else None),
            "family": res.family or "",
            "account": account,
            "model": model,
            "effort": res.effort or (live.effort if live else ""),
            "turns": res.usage.turns if res.usage else None,
            "secs": round(res.secs or 0),
            "cost": res.cost or 0.0,
            "t": time.time(),
            "stopped": stopped,
            "tokens": {"in": tk.in_, "cached": tk.cached, "out": tk.out} if tk else None,
            "denied": [
                {"kind": d.kind, "tool": d.tool, "path": d.path or "", "input": d.input, "reason": d.reason or ""} for d in res.denied
            ],
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
        if node == "write":  # session context telemetry for the trace
            told = res.usage.context_k if res.usage else None  # delegate says it, whatever the harness
            row["context_k"] = round(told) if told else None
        for k in KEYS:
            self.stats["tokens_" + k] += int((row["tokens"] or {}).get(k) or 0)
        self.sessions.append(row)
        tk = row["tokens"] or {}
        source = res.usage.cost_source if res.usage else "unknown"
        self.log.emit(
            CallEnd(
                id=cid,
                status=row["status"],
                reason=row["reason"],
                ref=row["ref"] or "",
                account=row["account"] or "",
                model=row["model"] or "",
                effort=row["effort"],
                secs=float(row["secs"]),
                cost=float(row["cost"]) if source != "unknown" else None,
                cost_source=source,
                tokens=CallTokens(in_=int(tk.get("in") or 0), cached=int(tk.get("cached") or 0), out=int(tk.get("out") or 0),
                                  cache_write=res.usage.tokens.cache_write if res.usage and res.usage.tokens else None),
                family=row["family"] or "",
                flag=row["flag"],
                exit=res.exit_code,
            )
        )
        return row
