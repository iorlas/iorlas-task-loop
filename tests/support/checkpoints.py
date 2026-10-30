"""Checkpoints as a test reads and arranges them: through the engine's own stores, never by JSON shape."""
from taskloop.adapters import ident
from taskloop.contracts import wire
from taskloop.contracts.checkpoint import Checkpoint, RunState
from taskloop.contracts.paths import ConfigDir
from taskloop.stores.real import real_stores


def read_ck(e, bead=None):
    """The stored Checkpoint of the engine's bead (or `bead`), or None."""
    return e.stores.checkpoints.of(bead or e.bead).get()


def put_ck(e, bead=None, head="", step="", run="r-0", **state):
    """A checkpoint as an earlier run left it: `state` fields go to the RunState."""
    e.stores.checkpoints.of(bead or e.bead).write(
        Checkpoint(bead=bead or e.bead, run=run, t=0.0, head=head, step=step, state=RunState(**state))
    )


def flat_ck(ck):
    """A checkpoint as one dict: the envelope's fields and the run state's, with the names a test reads (plan, brief)."""
    if ck is None:
        return None
    out = {k: v for k, v in wire.dump(ck).items() if k != "state"}
    out.update(ck.state.dump())
    w = ck.state.writer
    out.update(
        plan=ck.state.plan_data,
        brief=ck.state.brief_hash,
        writer=w.delegate or "",
        writer_ctx=w.ctx,
        writer_seen=w.seen,
    )
    return out


def stored_ck(bead="t-1"):
    """The stored Checkpoint of `bead` in the test's config dir, read through the real stores."""
    return real_stores(ConfigDir(ident.config_dir())).checkpoints.of(bead).get()
