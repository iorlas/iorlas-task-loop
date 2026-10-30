"""The dashboard's ports, made from the engine code: the read-only facts the package taskloop_dash may not import (the slot beads),
the owner's writes through the intake, and bd through the engine's adapter."""

import os
import shutil
from collections.abc import Callable
from typing import Any

from taskloop.adapters import ident
from taskloop.adapters.bd import BdStore
from taskloop.adapters.ident import config_dir
from taskloop.app.asks.intake import Intake
from taskloop.app.doctor import profiles
from taskloop.app.run.requests import OwnerVerbs
from taskloop.app.track.trail import now
from taskloop.app.wire import asks as wire_asks
from taskloop.app.wire import real
from taskloop.app.wire import slots as wslots
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.dash import Result, Stick
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.contracts.stores import AskStore, ReposStore
from taskloop_dash.env import Ports

DASH = Identity(actor="tl-dash")  # the dashboard's bd actor


def quiet(fn: Callable[..., Any], default: Any) -> Callable[..., Any]:
    """A port that never raises: tl.bd exits when bd is not on PATH."""
    def call(*a: Any) -> Any:
        try:
            return fn(*a)
        except (Exception, SystemExit):
            return default
    return call


def store(repo: str) -> BdStore:
    """The dashboard's bd: the engine's typed adapter (--actor, --json), the one process site."""
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    return BdStore(DASH.actor, repo or None, timeout=30)


def answer(repo: str, bead: BeadId, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
    """The dashboard's answer is `tl answer`'s: the same Intake (record, bead opened, receipt comment), only `by` is "dash"."""
    return owner_intake(wire_asks.store(), store, now)(repo).answer(bead, action, text, amend)


FACTORY_REPO = "iorlas-task-loop"  # a factory bead is filed in the registered repo of this name


def adrs_of(repo: str) -> AdrStore:
    return AdrStore.at(ConfigDir(config_dir()), repo)


def factory_store() -> Beads | None:
    """The tracker of the task-loop repo: the registered repo named `iorlas-task-loop`; None when none is registered."""
    index = ReposStore(ConfigDir(config_dir())).get()
    path = next((p for p in (index.repos if index else {}) if os.path.basename(p.rstrip("/")) == FACTORY_REPO and os.path.isdir(p)), "")
    return store(path) if path else None


def refused(why: str, ok: str = "") -> Result:
    return Result(ok=False, message=why) if why else Result(ok=True, message=ok)


def guarded(do: Callable[[], str]) -> Result:
    try:
        return refused(do())
    except BdFailure as err:
        return refused(f"bd did not answer ({(err.error.text.strip().splitlines() or ['no output'])[-1][:200]}). Nothing was changed.")
    except OSError as err:
        return refused(f"The dashboard cannot run bd ({err.strerror or err}). Nothing was changed.")


def ask_writes(intake: Callable[[str], Intake]) -> dict[str, Any]:
    """The ask ledger's writes: stick an answer, prune a decision, ask back."""
    def stick(repo: str, ask_id: str, outcome: str, text: str) -> Result:
        return guarded(lambda: intake(repo).stick(ask_id, Stick(outcome), text))

    def prune(repo: str, adr: str) -> Result:
        return guarded(lambda: intake(repo).prune(repo, adr))

    def ask_back(repo: str, bead: BeadId, ask_id: str, text: str) -> Result:
        return guarded(lambda: intake(repo).ask_back(bead, ask_id, text))
    return {"stick": stick, "prune": prune, "ask_back": ask_back}


def owner_writes(intake: Callable[[str], Intake], cfg: ConfigDir | None = None) -> dict[str, Any]:
    """The owner's writes the dashboard makes beyond an answer, as Ports fields: each is an in-process Intake verb of the repo's tracker
    (park, stop and note also a run's request file under `cfg`), its failure a Result the page shows. The dash runs no process and never
    sees a bd argv."""
    def look(repo: str, item: str, verdict: str, note: str, look_bead: str) -> Result:
        return guarded(lambda: intake(repo).look(item, verdict, note, look_bead)[1])

    def cause(repo: str, bead: BeadId, scope: str, why: str) -> Result:
        return guarded(lambda: intake(repo).cause(bead, scope, why))

    def ack(repo: str, bead: BeadId, scope: str, on: bool) -> Result:
        return guarded(lambda: intake(repo).ack(bead, scope, on))

    def run_verb(repo: str, do: Callable[[OwnerVerbs], tuple[str, str]]) -> Result:
        """A park, stop or note (app/run/requests.OwnerVerbs): its own words on success, the refusal otherwise."""
        said: list[str] = []

        def act() -> str:
            owner = intake(repo)
            why, ok = do(OwnerVerbs(owner, cfg or ConfigDir(ident.config_dir()), owner.now()))
            said.append(ok)
            return why
        out = guarded(act)
        return Result(ok=True, message=said[-1]) if out.ok and said else out

    def park(repo: str, bead: BeadId, run: str) -> Result:
        return run_verb(repo, lambda v: v.park(bead, run))

    def stop(repo: str, bead: BeadId, run: str) -> Result:
        return run_verb(repo, lambda v: v.stop(bead, run))

    def note(repo: str, bead: BeadId, run: str, text: str) -> Result:
        return run_verb(repo, lambda v: v.note(bead, run, text))
    return {"look": look, "cause": cause, "ack": ack, "park": park, "stop": stop, "note": note, **ask_writes(intake)}


def owner_intake(asks: AskStore, store_of: Callable[[str], Any], clock: Callable[[], float], by: str = "dash",
                 adrs: Callable[[str], AdrStore] | None = None, factory: Callable[[], Beads | None] | None = None
                 ) -> Callable[[str], Intake]:
    return lambda repo: Intake(asks, store_of(repo), clock, by, adrs, factory)


def slot_beads(repo: str) -> list[dict[str, Any]]:
    return [b.to_dict() for b in wslots.slot_beads(repo, DASH)]


def ports(env: Env) -> Ports:
    """`python3 -m taskloop_dash --ports taskloop.app.launch.dash_ports:ports`: the dashboard builds its ports from the engine's code."""
    git = real.git(env)

    def red_row(repo: str) -> str:
        return profiles.red_row(git, repo)

    return Ports(store=store, answer=answer,
                 **owner_writes(owner_intake(wire_asks.store(), store, now, adrs=adrs_of, factory=factory_store)),
                 slot_beads=quiet(slot_beads, []), profile_error=quiet(red_row, ""))
