"""The run's reflection (tl-05s): one cheap read-only call at the close that says what went well and badly."""
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from tlkernel import answers
from tlkernel import log as rec
from tlkernel.bead import Bead
from tlkernel.delegate import DelegateResult, RunRequest
from tlkernel.delegateport import Answer, Resolved, Seam
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.schema import unstrict
from tlkernel.stores import JsonlStore
from tlkernel.wire import Open

from taskloop.adapters import childenv
from taskloop.app.pipeline.ports import TrustRefusal
from taskloop.app.pipeline.reflect_prompt import REFLECT_PROMPT
from taskloop.domain.lanes import caps
from taskloop.domain.matchers import clip


class ReflectConfig(Protocol):
    @property
    def reflect(self) -> bool: ...
    @property
    def base(self) -> str: ...


class ReflectStore(Protocol):
    def show(self, bead: BeadId) -> Bead | None: ...


class ReflectDelegation(Protocol):
    def route(self, quiet: bool = False) -> str: ...


class ReflectCalls(Protocol):
    def start(self, step: str, node: str, role: str, resume: bool, n: int) -> str: ...
    def end(self, cid: str, node: str, role: str, tries: int, res: DelegateResult) -> Open: ...


class ReflectRouter(Protocol):
    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "") -> Seam | None: ...
    def call(self, resolved: Resolved | None, req: RunRequest, brief: str, schema: Open,
             runner: Seam | None, env: Mapping[str, str]) -> Answer: ...


class ReflectHost(Protocol):
    @property
    def cfg(self) -> ReflectConfig: ...
    dry: bool
    route: str
    stop_pending: bool
    sessions: list[Open]
    git: Git
    wt: str
    store: ReflectStore
    bead: BeadId
    bead_title: str
    session: str
    live_n: int
    err_path: Path
    resolved: Resolved | None
    env: Env
    stats: dict[str, int]
    log_path: Path

    @property
    def delegation(self) -> ReflectDelegation: ...
    @property
    def calls(self) -> ReflectCalls: ...
    @property
    def router(self) -> ReflectRouter: ...
    def warn(self, text: str) -> None: ...
    def live(self, step: str) -> str: ...


class Reflector:
    def __init__(self, host: ReflectHost, refusal: TrustRefusal) -> None:
        self.host = host
        self.refusal = refusal

    def worth_asking(self, why: str) -> bool:
        host = self.host
        if not host.cfg.reflect or host.dry or not host.route or host.stop_pending:
            return False
        if not any(s.get("node") in ("write", "review", "verify") for s in host.sessions):
            return False  # a run that only planned has nothing to reflect on
        return not why.startswith(("paused:", "waiting:", "failed: infrastructure", "failed: stopped"))

    def reflect_run(self, outcome: str, why: str) -> Open | None:
        """tl-05s: one cheap read-only call that reflects on this run: what went well and badly (each bad item with its cause class
        and the session it comes from), what wasted tokens or minutes, what to change. Never blocks or changes the outcome: any
        failure, a missing lane, a paused run, a stop, is no reflection. -> the answer dict or None."""
        host = self.host
        if not self.worth_asking(why):
            return None
        try:
            refusal = self.refusal.refusal(host.git, host.wt, host.cfg.base, host.store.show(host.bead))
            if refusal:
                host.warn("no reflection: " + refusal)
                return None
            prompt = self.reflect_prompt(outcome, why)
            over = caps.check("reviewer", prompt)
            if over is not None:  # never blocks the close: an over-cap reflection is no reflection
                host.warn(f"no reflection: {over.why('reflect')}")
                return None
            # a short wait: the close step ignores a stop while this runs (route.py adds 120 s to the limit)
            host.delegation.route()
            req = RunRequest(role="reviewer", brief_path="", cwd=host.wt, schema_path="", task=host.bead, parent=host.session,
                             title=f"{host.bead} · reflect", timeout_s=45)
            cid = host.calls.start("reflect", "reflect", "reviewer", False, host.live_n)
            runner = host.router.runner(host.err_path, None, host.live("reflect"))
            res = host.router.call(host.resolved, req, prompt, answers.sent_schema("reflect"), runner,
                                   childenv.delegate_call_env(host.env)).res
            saved = {k: v for k, v in host.stats.items() if k.startswith("tokens_")}
            host.calls.end(cid, "reflect", "reviewer", 1, res)
            host.stats.update(saved)  # the run's counts are the run's, as the Reflect comment says them
            if res.data is None or res.stop is not None:
                return None
            data = unstrict(res.data, answers.schema_for("reflect"))
            return None if answers.check("reflect", False, data) else data
        except Exception as err:  # nothing here may touch the run's outcome
            host.warn(f"no reflection: {type(err).__name__}: {str(err)[:160]}\n" + traceback.format_exc())
            return None

    def reflect_prompt(self, outcome: str, why: str) -> str:
        host = self.host
        rows = []
        for s in host.sessions:
            t = s.get("tokens") or {}
            rows.append(f"- {s.get('node')} ({s.get('role')}) {s.get('family') or '?'} {s.get('model') or '?'}: in {t.get('in') or 0}, "
                        f"cached {t.get('cached') or 0}, out {t.get('out') or 0}, {s.get('secs')}s, session {s.get('ref') or '(none)'}")
        lines = []
        for it in JsonlStore(host.log_path, rec.decode).read_from().items:
            if isinstance(it.rec, rec.Transition):
                lines.append(f"{it.rec.kind}: " + clip(f"{it.rec.cause} -> {it.rec.to}: {it.rec.detail}", 200))
            elif isinstance(it.rec, rec.Warn):
                lines.append(f"{it.rec.kind}: " + clip(it.rec.text, 200))
        stats = "; ".join(f"{k}={v}" for k, v in host.stats.items())
        return REFLECT_PROMPT % (host.bead, clip(host.bead_title, 120), outcome, clip(why or "(none)", 600), stats, "\n".join(rows[:40]),
                                 "\n".join(lines[-70:]) or "(none)")
