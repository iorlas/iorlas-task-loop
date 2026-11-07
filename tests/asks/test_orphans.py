"""A bead parked on an ask that was dropped at upgrade (a v1 or unreadable file) stays visible and is asked again."""
import json
import sys
from pathlib import Path

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.askjson import unreadable_ask
from support.fake_beads import FakeBeads
from support.tiers import domain

from taskloop.app.asks import ask_verbs as cli
from taskloop.app.asks import sweeps
from taskloop.app.asks.paths import ask_marker
from tlkernel.askstore import HAD_PICK, ORPHAN, AskStore
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir

T = 1000.0


@domain
class OrphanTest(Case):
    def setup_method(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name))
        unreadable_ask(self.cfg, "tl-7", json.dumps({"v": 1, "id": "tl-7-2", "bead": "tl-7", "status": "open", "kind": "verify"}))
        self.asks = AskStore.at(self.cfg)
        self.store = FakeBeads()
        self.store.beads[BeadId("tl-7")] = Bead(id=BeadId("tl-7"), title="t", status="blocked", labels=["needs-info"])

    def test_it_is_listed_with_the_one_typed_line(self) -> None:
        assert (self.asks.get(BeadId("tl-7")), self.asks.orphans()) == (None, ["tl-7"])
        out: list[str] = []
        assert cli.age(self.asks, T, out.append) == 0
        assert out == [sweeps.orphan_lines(self.asks)[0]]
        assert ORPHAN in out[0]
        listed: list[str] = []
        cli.run(cli.Arguments(op="list"), self.asks, lambda repo: self.store, lambda: T, "denis", self.cfg, listed.append)
        assert ORPHAN in listed[0]

    def test_the_loop_reopens_it_into_the_pick_queue_once(self) -> None:
        self.store.beads[BeadId("tl-7")].metadata[HAD_PICK] = "auto"  # the park took the label off
        marker = ask_marker(self.cfg, "orphans")
        assert sweeps.reask_orphans(self.asks, self.store, marker, T, "auto", "needs-info") == ["tl-7"]
        b = self.store.beads[BeadId("tl-7")]
        assert (b.status, "auto" in b.labels, "needs-info" in b.labels) == ("open", True, False)
        assert sweeps.reask_orphans(self.asks, self.store, marker, T + 1, "auto", "needs-info") == []  # throttled
        assert sweeps.reask_orphans(self.asks, self.store, marker, T + 1e4, "auto", "needs-info") == []  # no longer blocked

    def test_the_sweep_never_adds_a_pick_label_the_bead_did_not_have(self) -> None:
        marker = ask_marker(self.cfg, "orphans")
        assert sweeps.reask_orphans(self.asks, self.store, marker, T, "auto", "needs-info") == ["tl-7"]
        b = self.store.beads[BeadId("tl-7")]
        assert (b.status, b.labels) == ("open", [])

    def test_answer_rerun_reopens_it_and_a_closed_bead_drops_the_dead_file(self) -> None:
        out: list[str] = []
        code = cli.run(
            cli.Arguments(op="answer", bead=BeadId("tl-7"), text=(), rerun=True), self.asks, lambda repo: self.store, lambda: T, "denis",
            self.cfg, out.append
        )
        assert (code, self.store.beads[BeadId("tl-7")].status) == (0, "open")
        self.store.beads[BeadId("tl-7")] = Bead(id=BeadId("tl-7"), title="t", status="closed")
        sweeps.reopen(self.asks, self.store, BeadId("tl-7"))
        assert self.asks.orphans() == []
