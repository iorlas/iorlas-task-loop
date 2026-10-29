"""The run's reflection (tl-05s): one cheap read-only call at the close that says what went well and badly."""
from typing import Any

from taskloop.adapters import delegate as dg
from taskloop.contracts import answers
from taskloop.contracts import log as rec
from taskloop.contracts.delegate import RunRequest
from taskloop.contracts.schema import unstrict
from taskloop.contracts.stores import JsonlStore
from taskloop.domain.matchers import clip
from taskloop.domain.prompts.reflect import REFLECT_PROMPT


class Reflector:
    def __init__(self, host: Any) -> None:
        self.e = host

    def worth_asking(self, why: str) -> bool:
        e = self.e
        if not e.cfg.reflect or e.dry or not e.route or e.stop_pending:
            return False
        if not any(s.get("node") in ("write", "review", "verify") for s in e.sessions):
            return False  # a run that only planned has nothing to reflect on
        return not why.startswith(("paused:", "waiting:", "failed: infrastructure", "failed: stopped"))

    def reflect_run(self, outcome: str, why: str) -> dict[str, Any] | None:
        """tl-05s: one cheap read-only call that reflects on this run: what went well and badly (each bad item with its cause class
        and the session it comes from), what wasted tokens or minutes, what to change. Never blocks or changes the outcome: any
        failure, a missing lane, a paused run, a stop, is no reflection. -> the answer dict or None."""
        e = self.e
        if not self.worth_asking(why):
            return None
        try:
            prompt = self.reflect_prompt(outcome, why)
            # a short wait: the close step ignores a stop while this runs (route.py adds 120 s to the limit)
            e.delegation.route()
            req = RunRequest(role="reviewer", brief_path="", cwd=str(e.wt), schema_path="", task=e.bead, parent=e.session,
                             title=f"{e.bead} · reflect", timeout_s=45)
            cid = e.calls.start("reflect", "reflect", "reviewer", False, e.live_n)
            runner = e.router.runner(e.err_path, None, e.live("reflect"))
            res = dg.call(e.resolved, req, prompt, answers.sent_schema("reflect"), runner).res
            saved = {k: v for k, v in e.stats.items() if k.startswith("tokens_")}
            e.calls.end(cid, "reflect", "reviewer", 1, res)
            e.stats.update(saved)  # the run's counts are the run's, as the Reflect comment says them
            if res.data is None or res.stop is not None:
                return None
            data = unstrict(res.data, answers.schema_for("reflect"))
            return None if answers.check("reflect", False, data) else data
        except Exception as err:  # nothing here may touch the run's outcome
            e.warn(f"no reflection: {type(err).__name__}: {str(err)[:160]}")
            return None

    def reflect_prompt(self, outcome: str, why: str) -> str:
        e = self.e
        rows = []
        for s in e.sessions:
            t = s.get("tokens") or {}
            rows.append(f"- {s.get('node')} ({s.get('role')}) {s.get('family') or '?'} {s.get('model') or '?'}: in {t.get('in') or 0}, "
                        f"cached {t.get('cached') or 0}, out {t.get('out') or 0}, {s.get('secs')}s, session {s.get('ref') or '(none)'}")
        lines = []
        for it in JsonlStore(e.log_path, rec.decode).read_from().items:
            if isinstance(it.rec, rec.Transition):
                lines.append(f"{it.rec.kind}: " + clip(f"{it.rec.cause} -> {it.rec.to}: {it.rec.detail}", 200))
            elif isinstance(it.rec, rec.Warn):
                lines.append(f"{it.rec.kind}: " + clip(it.rec.text, 200))
        stats = "; ".join(f"{k}={v}" for k, v in e.stats.items())
        return REFLECT_PROMPT % (e.bead, clip(e.bead_title, 120), outcome, clip(why or "(none)", 600), stats, "\n".join(rows[:40]),
                                 "\n".join(lines[-70:]) or "(none)")
