"""The owner's `look` verb (Intake.look): good, redo and undo on a look item, over the typed bd port in memory."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.look_world import FakeBd, world

from taskloop.app.asks.intake import Intake
from taskloop.contracts import gallery
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore

NOW = 1_800_000_000.0


def intake(fake, tmp):
    return Intake(AskStore.at(tmp), fake, lambda: NOW, "dash")


class Look(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = ConfigDir(self.tmp.name)

    def look(self, fake, verdict, item="tl-1#1", note="", look_bead=""):
        return intake(fake, self.config).look(item, verdict, note, look_bead)

    def stored(self, fake):
        return {e["id"]: e for e in fake.beads["tl-look"].metadata["looks"]}

    def test_good_settles_the_item_and_keeps_the_other_metadata(self):
        fake = world("open", "open")
        self.assertEqual(self.look(fake, "good"), ("good", ""))
        e = self.stored(fake)["tl-1#1"]
        self.assertEqual((e["status"], e["answered"]), ("good", NOW))
        self.assertEqual(fake.beads[BeadId("tl-look")].metadata["other"], 1)
        self.assertEqual(fake.beads[BeadId("tl-look")].status, "open")  # one item still waits

    def test_the_last_good_closes_the_look_bead(self):
        fake = world("good", "open")
        self.look(fake, "good", item="tl-1#2")
        self.assertEqual(fake.beads[BeadId("tl-look")].status, "closed")

    def test_redo_files_a_bead_with_the_note_and_the_pictures(self):
        fake = world("open")
        status, why = self.look(fake, "redo", note="  the title is too small  ")
        self.assertEqual((status, why), ("redo", ""))
        e = self.stored(fake)["tl-1#1"]
        made = fake.beads[e["redo_bead"]]
        self.assertIn("the title is too small", made.description)
        self.assertIn("docs/evidence/tl-1/m1.png (after)", made.description)
        self.assertIn("docs/evidence/tl-1/m1-before.png (before)", made.description)
        self.assertEqual([d.id for d in made.dependencies], ["related:tl-1"])
        self.assertEqual(e["answer_note"], "the title is too small")
        self.assertEqual(fake.beads[BeadId("tl-look")].status, "closed")  # nothing waits any more

    def test_redo_with_an_empty_note_is_refused_and_files_nothing(self):
        fake = world("open")
        for note in ("", "   "):
            status, why = self.look(fake, "redo", note=note)
            self.assertEqual((status, why), ("", "Write what to change first."))
        self.assertFalse(any(c[0] in ("create", "update-meta") for c in fake.calls))

    def test_a_second_answer_is_refused_until_the_first_is_taken_back(self):
        fake = world("open")
        self.look(fake, "good")
        status, why = self.look(fake, "redo", note="n")
        self.assertEqual((status, why[:16]), ("", "Already answered"))
        self.assertFalse(any(c[0] == "create" for c in fake.calls))

    def test_undo_of_good_reopens_item_and_bead(self):
        fake = world("open")
        self.look(fake, "good")
        self.assertEqual(fake.beads[BeadId("tl-look")].status, "closed")
        self.assertEqual(self.look(fake, "undo"), ("open", ""))
        self.assertEqual((self.stored(fake)["tl-1#1"]["status"], fake.beads[BeadId("tl-look")].status), ("open", "open"))

    def test_undo_of_redo_closes_the_follow_up(self):
        fake = world("open")
        self.look(fake, "redo", note="n")
        made = self.stored(fake)["tl-1#1"]["redo_bead"]
        self.look(fake, "undo")
        self.assertEqual(fake.beads[made].status, "closed")
        e = self.stored(fake)["tl-1#1"]
        self.assertEqual((e["status"], e["redo_bead"]), ("open", ""))

    def test_undo_of_an_open_item_changes_nothing(self):
        fake = world("open")
        self.assertEqual(self.look(fake, "undo"), ("open", ""))
        self.assertFalse(any(c[0] in ("close", "create", "update-meta") for c in fake.calls))

    def test_the_item_is_found_by_its_id_or_by_a_source_bead_with_one_waiting_item(self):
        fake = world("open")
        self.assertEqual(self.look(fake, "good", item="tl-1")[0], "good")  # the source bead, one item waiting
        fake = world("open", "open")
        self.assertEqual(self.look(fake, "good", item="tl-1")[0], "")  # two items: ambiguous, refused
        self.assertEqual(self.look(fake, "good", item="tl-1#2")[0], "good")

    def test_unknown_item_bead_and_verdict(self):
        fake = world("open")
        self.assertEqual(self.look(fake, "good", item="tl-1#9")[1], "That item is gone. Reload the page.")
        self.assertIn("no longer exists", self.look(fake, "good", look_bead="nope")[1])
        self.assertEqual(self.look(fake, "maybe")[0], "")
        fake.beads[BeadId("plain")] = Bead(id=BeadId("plain"), title="", status="open", labels=["auto"], metadata={"looks": []})
        self.assertIn("no longer exists", self.look(fake, "good", look_bead="plain")[1])  # not an owner-look bead: never touched

    def test_an_old_description_bead_is_turned_into_metadata_by_the_first_answer(self):
        desc = "## tl-9: Settings\n- docs/e/tl-9/a.png\n"
        fake = FakeBd({"tl-look": {"id": "tl-look", "title": "", "status": "open", "labels": [gallery.LABEL], "description": desc}})
        self.assertEqual(self.look(fake, "good", item="tl-9#0"), ("good", ""))
        self.assertEqual(fake.beads[BeadId("tl-look")].metadata["looks"][0]["status"], "good")

    def test_bd_failing_reports_and_changes_nothing_else(self):
        fake = world("open")
        fake.refuse = {"update-meta"}
        status, why = self.look(fake, "good")
        self.assertEqual(status, "")
        self.assertIn("bd refused the answer", why)
        self.assertEqual(fake.beads[BeadId("tl-look")].status, "open")

    def test_a_failed_save_closes_the_redo_bead_it_made(self):
        fake = world("open")
        fake.refuse = {"update-meta"}
        self.assertEqual(self.look(fake, "redo", note="n")[0], "")
        self.assertEqual(fake.beads[BeadId("tl-r-2")].status, "closed")

    def test_two_clicks_at_once_file_one_follow_up(self):
        fake = world("open")
        res = []
        ts = [threading.Thread(target=lambda: res.append(self.look(fake, "redo", note="n")[0])) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(res), ["", "", "", "redo"])
        self.assertEqual(sum(1 for c in fake.calls if c[0] == "create"), 1)

    def test_an_odd_redo_id_is_never_closed(self):
        fake = world("open")
        fake.beads[BeadId("tl-look")].metadata["looks"][0].update(status="redo", redo_bead="--force")
        self.look(fake, "undo")
        self.assertFalse(any(c == ("close", "--force") for c in fake.calls))


if __name__ == "__main__":
    unittest.main()
