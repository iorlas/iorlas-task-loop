"""Calls: the worker calls of a run. A call opens with its start record and closes with the end record and one row of the run's
sessions (the trace's `sessions`), so a reflection and the report read what the dashboard drew."""
import time
from collections.abc import Callable
from typing import Any

from taskloop.contracts.log import CallEnd, CallStart
from taskloop.contracts.trace import Tokens
from taskloop.stores.runlog import RunLog

KEYS = ("in", "cached", "out")


def timing(obs: dict[str, Any]) -> dict[str, Any]:
    """The process boundaries of a call as the log records them: started, ended, first provider error, last output, kill."""
    return {k: obs.get(k) for k in ("started_t", "ended_t", "first_error_t", "last_event_t", "kill_t")}


class Calls:
    def __init__(self, log: RunLog, node_id: Callable[[], int | None], sessions: list[dict[str, Any]], stats: dict[str, int],
                 opencode: Callable[[str], str], context_tokens: Callable[[str], int | None]) -> None:
        self.log, self.node_id, self.sessions, self.stats = log, node_id, sessions, stats
        self.opencode, self.context_tokens = opencode, context_tokens  # a ref -> OpenCode's session id ('' if none); a transcript -> tokens

    def start(self, step: str, node: str, role: str, resume: bool, n: int) -> str:
        """The call is about to be made: its id, which the end record carries."""
        cid = self.log.next_id("c")
        nid = self.node_id()
        self.log.emit(CallStart(id=cid, n=n, step=step, node="n%d" % nid if nid else "", role=role, resume=resume))
        return cid

    def end(self, cid: str, node: str, role: str, tries: int, res: Any, stopped: str = "", resume: bool = False,
            prompt_chars: int | None = None) -> dict[str, Any]:
        """The call ended (done or stopped): its record, its session row, the run's token counts."""
        j, st = res.raw or {}, res.stop
        row = {"node": node, "role": role, "attempt": tries, "status": "done" if st is None else "stopped",
               "ref": res.ref, "run_id": res.run_id, "transcript": j.get("transcript") or "",
               "family": res.family, "lane": res.lane, "model": res.model,
               "effort": j.get("effort") or "", "turns": j.get("turns") or (res.usage or {}).get("turns"), "secs": round(res.secs or 0),
               "cost": res.cost or 0.0, "t": time.time(), "stopped": stopped, "tokens": j.get("tokens"),
               "denied": j.get("denied") or [], "reason": st.reason if st else None,
               "stop": {"scope": st.scope, "permanence": st.permanence, "retry": st.retry_kind} if st else None,
               "warning": j.get("warning"), "context": j.get("context"), "node_id": self.node_id(), "resume": resume,
               "flag": j.get("flag"), "prompt_chars": prompt_chars}
        if node == "write":  # where the session's context stands now: what the next round weighs against write_fresh_above_k
            if not row["transcript"] and self.opencode(row["ref"]):  # OpenCode: the session id stands for the transcript
                row["transcript"] = "opencode:" + self.opencode(row["ref"])
            tok = self.context_tokens(row["transcript"])
            row["context_k"] = round(tok / 1000) if tok else None
        for k in KEYS:
            self.stats["tokens_" + k] += int((row["tokens"] or {}).get(k) or 0)
        self.sessions.append(row)
        tk = row["tokens"] or {}
        self.log.emit(CallEnd(id=cid, status=row["status"], reason=row["reason"], ref=row["ref"] or "", lane=row["lane"] or "",
                              model=row["model"] or "", effort=row["effort"], secs=float(row["secs"]), cost=float(row["cost"]),
                              tokens=Tokens(in_=int(tk.get("in") or 0), cached=int(tk.get("cached") or 0), out=int(tk.get("out") or 0)),
                              family=row["family"] or "", flag=row["flag"], transcript=row["transcript"]))
        return row
