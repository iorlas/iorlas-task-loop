"""Checkpoints as a test reads and arranges them: through the engine's own stores, never by JSON shape."""
from support import homes
from taskloop.stores.real import real_stores
from tlkernel import wire
from tlkernel.checkpoint import Checkpoint, RunState


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
    return real_stores(homes.cfg()).checkpoints.of(bead).get()


def drop_ck(bead):
    """The stored checkpoint of `bead` gone (a new bead for the next case)."""
    real_stores(homes.cfg()).checkpoints.of(bead).delete()
