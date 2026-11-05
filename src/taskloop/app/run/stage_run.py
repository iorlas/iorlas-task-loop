"""The shared lifecycle of engine runs and standalone stage verbs."""
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from taskloop.contracts import log as rec
from taskloop.contracts.finish import finish_run, previous_finish
from taskloop.contracts.finish_projection import history
from taskloop.contracts.identity import Identity
from taskloop.contracts.locator import RunBundle, RunLocator, host_name
from taskloop.contracts.run import RunFinish, RunManifest, RunState
from taskloop.contracts.runlife import BEAT_EVERY
from taskloop.stores.bundle import Stores
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog


@dataclass
class StageRun:
    bundle: RunBundle
    log: RunLog
    stores: Stores
    rc: int = 1
    continued: bool = False
    reason: str = ""
    terminal: RunState | None = None
    answer: RunFinish | None = None  # a one-stage run's own answer (staged, landed, done); else the state alone says it


@contextmanager
def stage_run(who: Identity, repo: str, mode: str, *, bundle: RunBundle | None = None,
              events: bool = True, stores: Stores | None = None, log: RunLog | None = None) -> Generator[StageRun]:
    """Open before doing work; keep evidence and record a terminal state on every exit, including exceptions."""
    locator = RunLocator(who.config)
    if bundle is None:
        bundle = locator.create(repo, "", time.time(), mode=mode, owner=who.actor, session=who.session)
    else:
        locator.identify(bundle.run, mode, who.actor, who.session)
    stopped = threading.Event()
    helper: threading.Thread | None = None
    rc, reason = 1, "stage interrupted"
    stage: StageRun | None = None
    try:
        stores = stores or real_stores(who.config)
        log = log or RunLog(stores.run_log(bundle.run), run_id=bundle.run, host=host_name())
        stage = StageRun(bundle, log, stores)
        locator.beat(bundle.run, time.time())

        def heartbeat() -> None:
            while not stopped.wait(BEAT_EVERY):
                locator.beat(bundle.run, time.time())

        helper = threading.Thread(target=heartbeat, daemon=True)
        helper.start()
        if events:
            log.emit(rec.RunStart(worktree=repo, mode=mode, owner=who.actor, session=who.session))
        try:
            yield stage
        except BaseException as exc:
            reason = str(exc) or type(exc).__name__
            log.warn(reason)
            raise
        else:
            rc, reason = stage.rc, stage.reason or ("" if stage.rc == 0 else f"exit {stage.rc}")
    except BaseException:
        rc = 1
        raise
    finally:
        stopped.set()
        if helper is not None and helper.ident is not None:
            helper.join()
        if stage is None or not stage.continued:
            terminal = stage.terminal if stage is not None else None
            state = terminal or (RunState.DONE if rc == 0 else RunState.FAILED)
            candidate = (stage.answer if stage is not None and stage.answer is not None and rc == 0 else
                         previous_finish(bundle.manifest.replace(state=state, ended=time.time(), reason=reason, finish=None)))
            finished_stage = stage

            def project(m: RunManifest, r: RunFinish) -> None:
                if finished_stage is None:
                    history(who.config, m, r, with_trace=False, index=False)
                else:
                    history(who.config, m, r, emit=finished_stage.log.emit,
                            append_trace=finished_stage.stores.traces.append, with_trace=False, index=False)

            finish_run(who.config, bundle.run, candidate, project)
