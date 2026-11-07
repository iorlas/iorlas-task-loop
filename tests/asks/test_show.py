"""The ask node presents the v3 fields and unknown-id errors."""
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fake_beads import FakeBeads

from taskloop.app.asks import ask_verbs
from tlkernel.ask import Ask, SimilarRef, ThreadEntry
from tlkernel.askenums import AskClass, AskKind, AskStatus
from tlkernel.askstore import AskStore
from tlkernel.dash import OwnerCause
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir

BEAD, RUN, T = "t-1", "t-1-20261026-100000", 5000.0


class Show(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.asks = AskStore.at(self.cfg)
        self.out: list[str] = []

    def ask(self, t=T + 1):
        a = Ask(id="t-1-1", n=1, bead=BeadId(BEAD), kind=AskKind.DECISION, ask_class=AskClass.OPEN_QUESTION, decision="Keep v1?",
                run=RUN, t=t,
                status=AskStatus.OPEN)
        self.asks.put(a)
        return a

    def show(self, key):
        rc = ask_verbs.run(ask_verbs.Arguments(op="show", bead=BeadId(key)), self.asks, lambda _r: FakeBeads(), lambda: T,
                           "x", self.cfg, self.out.append)
        return rc

    def test_prints_the_v3_fields(self):
        a = self.ask().replace(owner_cause=OwnerCause.DECISION, blocking=False, default="keep v1",
                                similar=[SimilarRef(kind="adr", id="adr-3")], thread=[ThreadEntry(by="owner", t=1.0, md="why?")])
        self.asks.put(a)
        for key in ("t-1-1", BEAD):
            self.out.clear()
            assert self.show(key) == 0
            text = "\n".join(self.out)
            for want in ("question: Keep v1?", "owner cause: decision", "blocking: no", "default: keep v1", "adr adr-3", "[owner] why?",
                         "outcome: -"):
                assert want in text

    def test_an_unknown_id_is_one_line_and_nonzero(self):
        assert (self.show("nope"), self.out) == (1, ["tl: no ask nope"])
