"""R16: Kind/POLICY exhaustiveness, apply, the storm detector and loop_health (tl-7y6.2.1/2/3)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
import clock  # noqa: E402
import loop_health as lh  # noqa: E402
import outcome as oc  # noqa: E402
from outcome import Kind, POLICY  # noqa: E402


class Table(unittest.TestCase):
    def test_twenty_two_kinds_and_no_ask_verify(self):
        self.assertEqual(len(Kind), 22)
        self.assertNotIn("ASK_VERIFY", Kind.__members__)
        self.assertNotIn("OTHER", Kind.__members__)

    def test_every_kind_has_a_policy_row_and_no_row_is_extra(self):
        self.assertEqual(set(POLICY), set(Kind))

    def test_table_by_family(self):
        for k, r in POLICY.items():
            fam = k.name.split("_")[0]
            self.assertEqual(r.makes_ask, fam == "ASK", k)
            self.assertEqual(r.storm, fam == "FAULT", k)
            if fam == "FAULT":
                self.assertEqual((r.bd, r.loop, r.label), ("open", "failed", "engine-fault"), k)
            if fam == "PAUSE":
                self.assertEqual((r.bd, r.loop, r.retries, r.replan), ("open", "paused", 0, False), k)
            if fam == "ASK":
                self.assertEqual((r.bd, r.loop), ("block", "parked"), k)
        self.assertEqual(POLICY[Kind.LANDED].loop, "landed")
        self.assertEqual(POLICY[Kind.WAIT_ASK].bd, "none")

    def test_network_is_paused_not_failed_and_counts_toward_nothing(self):
        r = POLICY[Kind.PAUSE_NETWORK]
        self.assertEqual((r.loop, r.trace, r.makes_ask, r.storm, r.retries, r.replan, r.escalate_to),
                         ("paused", "paused", False, False, 0, False, None))
        self.assertNotEqual(POLICY[Kind.PAUSE_NETWORK].trace, POLICY[Kind.ASK_STUCK].trace)  # paused vs parked

    def test_a_fault_has_no_ask_cell_and_escalates_only_to_stuck(self):
        for k in oc.FAULTS:
            self.assertIn(POLICY[k].escalate_to, (None, Kind.ASK_STUCK))

    def test_unknown_kind_or_newer_version_loads_as_engine_fault(self):
        for o in (oc.load("nope", detail="x"), oc.load("fault_infra", v=9, detail="y")):
            self.assertEqual(o.kind, Kind.FAULT_ENGINE)
        self.assertEqual(oc.load("pause_lane").kind, Kind.PAUSE_LANE)

    def test_fingerprint_strips_ids_numbers_and_paths(self):
        a = oc.fingerprint(Kind.FAULT_INFRA, "failed: write step /a/b/c.cs lifesim-d5f.46 exit 12")
        b = oc.fingerprint(Kind.FAULT_INFRA, "failed: write step /x/y/z.cs lifesim-fld.2 exit 7")
        self.assertEqual(a, b)
        self.assertNotEqual(a, oc.fingerprint(Kind.FAULT_SLOT, "failed: write step /a/b/c.cs lifesim-d5f.46 exit 12"))
        self.assertEqual(oc.fingerprint(Kind.LANDED, "x"), "")


def row(bead, kind, fp, t):
    return {"bead": bead, "kind": kind.value, "fingerprint": fp, "t": t}


class Apply(unittest.TestCase):
    def test_a_fault_leaves_the_bead_open_with_a_label_and_no_ask(self):
        o = oc.make(Kind.FAULT_BAD_REQUEST, "schema rejected")
        d = oc.apply(o, "b1", [], 1000.0)
        self.assertEqual((d.bd, d.label, d.loop_result, d.ask, d.escalated), ("open", "engine-fault", "failed", False, False))

    def test_third_identical_fault_on_one_bead_raises_exactly_one_ask(self):
        o = oc.make(Kind.FAULT_INFRA, "boom")
        h = [row("b", Kind.FAULT_INFRA, o.fingerprint, 1.0), row("b", Kind.FAULT_INFRA, o.fingerprint, 2.0)]
        d = oc.apply(o, "b", h, 3.0)
        self.assertEqual((d.kind, d.ask, d.escalated, d.bd), (Kind.ASK_STUCK, True, True, "block"))
        h.append(row("b", Kind.ASK_STUCK, o.fingerprint, 3.0))  # the ask is in history: the count starts again
        self.assertFalse(oc.apply(o, "b", h, 4.0).ask)
        other = [row("c", Kind.FAULT_INFRA, o.fingerprint, 1.0)] * 5  # other beads never escalate this one
        self.assertFalse(oc.apply(o, "b", other, 4.0).ask)

    def test_a_pause_is_never_escalated_however_often(self):
        o = oc.make(Kind.PAUSE_NETWORK, "Reconnecting... waiting for network")
        h = [row("b", Kind.PAUSE_NETWORK, o.fingerprint, float(i)) for i in range(20)]
        d = oc.apply(o, "b", h, 30.0)
        self.assertEqual((d.kind, d.ask, d.escalated, d.loop_result), (Kind.PAUSE_NETWORK, False, False, "paused"))

    def test_comment_is_deduped_per_bead_kind_fingerprint_per_hour(self):
        o = oc.make(Kind.PAUSE_LANE, "no lane for write")
        h = [row("b", Kind.PAUSE_LANE, o.fingerprint, 1000.0)]
        self.assertFalse(oc.apply(o, "b", h, 2000.0).comment)
        self.assertTrue(oc.apply(o, "b", h, 1000.0 + 3601).comment)
        self.assertTrue(oc.apply(o, "c", h, 2000.0).comment)

    def test_apply_is_pure(self):
        o, h = oc.make(Kind.FAULT_SLOT, "dirty"), [row("b", Kind.FAULT_SLOT, "x", 1.0)]
        self.assertEqual(oc.apply(o, "b", h, 5.0), oc.apply(o, "b", h, 5.0))
        self.assertEqual(len(h), 1)


class Storm(unittest.TestCase):
    def test_same_fingerprint_on_two_beads_inside_the_window_trips(self):
        c = clock.FakeClock()
        fp = oc.fingerprint(Kind.FAULT_BAD_REQUEST, "schema")
        h = [row("a", Kind.FAULT_BAD_REQUEST, fp, c.now())]
        self.assertIsNone(lh.storm_trip([], "a", Kind.FAULT_BAD_REQUEST, fp, c.now()))
        c.advance(60)
        trip = lh.storm_trip(h, "b", Kind.FAULT_BAD_REQUEST, fp, c.now())
        self.assertEqual(trip.beads, ("a", "b"))
        self.assertIn("STOPPED: storm", lh.banner(trip))
        self.assertIsNone(lh.storm_trip(h, "a", Kind.FAULT_BAD_REQUEST, fp, c.now()))  # one bead repeating is no storm
        c.advance(1800)
        self.assertIsNone(lh.storm_trip(h, "b", Kind.FAULT_BAD_REQUEST, fp, c.now()))  # outside the window

    def test_distinct_fingerprints_never_trip_and_non_faults_never_count(self):
        h = [row("a", Kind.FAULT_INFRA, oc.fingerprint(Kind.FAULT_INFRA, "one"), 10.0)]
        self.assertIsNone(lh.storm_trip(h, "b", Kind.FAULT_INFRA, oc.fingerprint(Kind.FAULT_INFRA, "two"), 20.0))
        for k in (Kind.PAUSE_NETWORK, Kind.PAUSE_KILLED, Kind.PAUSE_LANE, Kind.ASK_DECISION):
            fp = oc.fingerprint(k, "same")
            self.assertIsNone(lh.storm_trip([row("a", k, fp, 10.0)], "b", k, fp, 20.0), k)

    def test_the_record_is_written_once_and_expires(self):
        import tempfile
        p = lh.storm_path(tempfile.mkdtemp(), "repo")
        trip = lh.StormTrip("fp", ("a", "b"), 100.0)
        self.assertTrue(lh.write_storm(p, trip, 100.0))
        self.assertFalse(lh.write_storm(p, trip, 150.0))
        self.assertIsNone(lh.read_storm(p, 100.0 + 1800))
        lh.clear_storm(p)
        self.assertTrue(lh.write_storm(p, trip, 150.0))


class Health(unittest.TestCase):
    def test_four_rows(self):
        self.assertEqual(lh.loop_health(1, 5, 0, 1000).verdict, "ok")
        self.assertEqual(lh.loop_health(0, 0, 0, 1000).verdict, "idle_ok")
        self.assertEqual(lh.loop_health(0, 3, 900, 1000).verdict, "idle_ok")
        self.assertEqual(lh.loop_health(0, 3, 100, 1000).verdict, "absent")


if __name__ == "__main__":
    unittest.main()
