"""The ask ledger is the bead's comments: a row the owner's verbs cause is a comment first, and the table rebuilds from the comments."""
import contextlib

import support.paths  # noqa: F401
from support.fake_beads import FakeBeads

from taskloop.app.asks import intake, ledgercomments, raiser
from taskloop.domain.asks import specs
from tlkernel.askrows import AskRows
from tlkernel.askstore import AskStore
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir

BEAD = BeadId("t-1")
OPTS = [{"label": "Keep v1", "cost": "none", "answer": "keep v1", "recommended": True},
        {"label": "Migrate", "cost": "a run", "answer": "migrate", "recommended": False}]


def world(workdir):
    asks = AskStore.at(ConfigDir(workdir))
    beads = FakeBeads()
    beads.beads[BEAD] = Bead(id=BEAD, title="Saves", status="blocked", description="Keep saves working.")
    verbs = intake.Intake(asks, beads, lambda: 2000.0, "denis")
    raiser.raise_ask(asks, specs.open_question("Which save format?", OPTS), raiser.Asking(
        bead=BEAD, run="r", brief_hash="h", repo="/r/demo", title="Saves", now=1000.0))
    verbs.answer(BEAD, "text", "keep v1")
    return asks, beads


def test_an_owner_verb_leaves_its_ledger_row_as_a_comment_first(workdir):
    asks, beads = world(workdir)
    held = [e for c in beads.comments(BEAD) if (e := ledgercomments.parse(c.text)) is not None]
    assert [e.event for e in held] == ["raise", "answer"]  # every row of a store an Intake holds
    assert held == asks.rows()


def test_the_table_rebuilds_from_the_comments_to_the_same_view(workdir):
    asks, beads = world(workdir)
    before = asks.rows()
    rows = AskRows(ConfigDir(workdir))  # the table lost
    with rows.transaction():
        rows.connection().execute("DELETE FROM ask_ledger")
    assert asks.rows() == []
    assert ledgercomments.rebuild(asks, beads, [BEAD]) == 2
    assert asks.rows() == before
    assert ledgercomments.rebuild(asks, beads, [BEAD]) == 0  # rebuilding again adds nothing


def test_a_comment_that_cannot_be_written_leaves_no_row(workdir):
    asks, beads = world(workdir)
    rows = asks.rows()

    def refuse(bead, text):
        raise BdFailure(BdError(kind="other", text="bd down"))
    beads.add_comment = refuse
    ask = asks.get(BEAD)
    assert ask is not None
    with contextlib.suppress(BdFailure):
        asks.log(ask, "answer", 3000.0)
    assert asks.rows() == rows
