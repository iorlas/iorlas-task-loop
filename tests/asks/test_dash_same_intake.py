"""One code path: an answer from the dashboard and `tl answer` leave the same ask record and the same bead comments."""
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashes import make_dash
from support.fake_beads import FakeBeads
from support.narrow import must

from asks.dash_ports import answering
from asks.samples import MOCKS
from taskloop.app.asks import ask_verbs as cli_asks
from taskloop.app.asks import ledgercomments
from tlkernel.askstore import AskStore
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir

ASK = MOCKS["lifesim-22b3"].replace(bead="b-1", id="b-1-1")


def world(root: str):
    store = FakeBeads()
    store.beads[BeadId("b-1")] = Bead(id=BeadId("b-1"), title="", status="blocked")
    asks = AskStore.at(ConfigDir(root))
    asks.put(ASK)
    return store, asks


class SameIntake(Case):
    def test_the_dash_and_tl_answer_file_the_same_record_and_comments(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            tl_store, tl_asks = world(a)
            dash_store, dash_asks = world(b)
            args = cli_asks.Arguments(op="answer", bead=BeadId("b-1"), text=("go", "with", "A"),
                             amend=False, option=None, rerun=False, confirm=False,
                             split=False, verdict=None)
            cli_asks.run(args, tl_asks, lambda repo: tl_store, lambda: 1000.0, "dash", ConfigDir(a), lambda _line: None)
            dash = make_dash(answering(lambda repo: dash_store, b), config=b)
            req = {"project": "b", "ask": "b-1-1", "kind": "answer", "text": "go with A"}
            assert dash.writes.post("answer", req) == (200, {"ok": True, "message": "", "receipt": ""})
            def said(store):  # the ledger comment carries the clock of its path: compared apart from its t
                texts = [c.text for c in store.comments(BeadId("b-1"))]
                return [t for t in texts if not t.startswith(ledgercomments.PREFIX)], [
                    must(ledgercomments.parse(t)).replace(t=0.0) for t in texts if t.startswith(ledgercomments.PREFIX)]
            assert said(dash_store) == said(tl_store)
            assert "Owner (tl) answer" in said(dash_store)[0][0]
            assert dash_store.beads[BeadId("b-1")].status == tl_store.beads[BeadId("b-1")].status
            mine, theirs = dash_asks.get(BeadId("b-1")), tl_asks.get(BeadId("b-1"))
            assert must(must(mine).answer).replace(t=0) == must(must(theirs).answer).replace(t=0)
