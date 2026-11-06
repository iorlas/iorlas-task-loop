"""R16: Kind/POLICY exhaustiveness, apply and the storm detector (tl-7y6.2.1/2/3)."""
import json
import sys
from pathlib import Path

from support.case import Case
from support.tmpdir import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support.fake_clock import FakeClock
from support.narrow import must

from taskloop.adapters import storm as storm_file
from taskloop.contracts.kinds import FAULTS, Kind
from taskloop.domain import outcome as oc
from taskloop.domain import storm as lh
from taskloop.domain.outcome import POLICY


class Table(Case):
    def test_twenty_seven_kinds_and_no_ask_verify(self):
        assert len(Kind) == 27
        assert "ASK_VERIFY" not in Kind.__members__
        assert "OTHER" not in Kind.__members__

    def test_every_kind_has_a_policy_row_and_no_row_is_extra(self):
        assert set(POLICY) == set(Kind)

    def test_table_by_family(self):
        for k, r in POLICY.items():
            fam = k.name.split("_")[0]
            assert r.makes_ask == (fam == "ASK"), k
            assert r.storm == (fam == "FAULT"), k
            if fam == "FAULT":
                assert (r.bd, r.loop, r.label) == ("open", "failed", "engine-fault"), k
            if fam == "PAUSE":
                assert (r.bd, r.loop, r.retries, r.replan) == ("open", "paused", 0, False), k
            if fam == "ASK":
                assert (r.bd, r.loop) == ("block", "parked"), k
        assert POLICY[Kind.LANDED].loop == "landed"
        assert POLICY[Kind.WAIT_ASK].bd == "none"

    def test_network_is_paused_not_failed_and_counts_toward_nothing(self):
        r = POLICY[Kind.PAUSE_NETWORK]
        assert (
            (r.loop, r.trace, r.makes_ask, r.storm, r.retries, r.replan, r.escalate_to)
            == ("paused", "paused", False, False, 0, False, None)
        )
        assert POLICY[Kind.PAUSE_NETWORK].trace != POLICY[Kind.ASK_STUCK].trace  # paused vs parked

    def test_a_fault_has_no_ask_cell_and_escalates_only_to_stuck(self):
        for k in FAULTS:
            assert POLICY[k].escalate_to in (None, Kind.ASK_STUCK)

    def test_fingerprint_strips_ids_numbers_and_paths(self):
        a = oc.fingerprint(Kind.FAULT_INFRA, "failed: write step /a/b/c.cs lifesim-d5f.46 exit 12")
        b = oc.fingerprint(Kind.FAULT_INFRA, "failed: write step /x/y/z.cs lifesim-fld.2 exit 7")
        assert a == b
        assert a != oc.fingerprint(Kind.FAULT_SLOT, "failed: write step /a/b/c.cs lifesim-d5f.46 exit 12")
        assert oc.fingerprint(Kind.LANDED, "x") == ""


def row(bead, kind, fp, t):
    return {"bead": bead, "kind": kind.value, "fingerprint": fp, "t": t}


class Apply(Case):
    def test_a_fault_leaves_the_bead_open_with_a_label_and_no_ask(self):
        o = oc.make(Kind.FAULT_BAD_REQUEST, "schema rejected")
        d = oc.apply(o, "b1", [], 1000.0)
        assert (d.bd, d.label, d.loop_result, d.ask, d.escalated) == ("open", "engine-fault", "failed", False, False)

    def test_third_identical_fault_on_one_bead_raises_exactly_one_ask(self):
        o = oc.make(Kind.FAULT_INFRA, "boom")
        h = [row("b", Kind.FAULT_INFRA, o.fingerprint, 1.0), row("b", Kind.FAULT_INFRA, o.fingerprint, 2.0)]
        d = oc.apply(o, "b", h, 3.0)
        assert (d.kind, d.ask, d.escalated, d.bd) == (Kind.ASK_STUCK, True, True, "block")
        h.append(row("b", Kind.ASK_STUCK, o.fingerprint, 3.0))  # the ask is in history: the count starts again
        assert not oc.apply(o, "b", h, 4.0).ask
        other = [row("c", Kind.FAULT_INFRA, o.fingerprint, 1.0)] * 5  # other beads never escalate this one
        assert not oc.apply(o, "b", other, 4.0).ask

    def test_a_pause_is_never_escalated_however_often(self):
        o = oc.make(Kind.PAUSE_NETWORK, "Reconnecting... waiting for network")
        h = [row("b", Kind.PAUSE_NETWORK, o.fingerprint, float(i)) for i in range(20)]
        d = oc.apply(o, "b", h, 30.0)
        assert (d.kind, d.ask, d.escalated, d.loop_result) == (Kind.PAUSE_NETWORK, False, False, "paused")

    def test_comment_is_deduped_per_bead_kind_fingerprint_per_hour(self):
        o = oc.make(Kind.PAUSE_LANE, "no lane for write")
        h = [row("b", Kind.PAUSE_LANE, o.fingerprint, 1000.0)]
        assert not oc.apply(o, "b", h, 2000.0).comment
        assert oc.apply(o, "b", h, 1000.0 + 3601).comment
        assert oc.apply(o, "c", h, 2000.0).comment

    def test_apply_is_pure(self):
        o, h = oc.make(Kind.FAULT_SLOT, "dirty"), [row("b", Kind.FAULT_SLOT, "x", 1.0)]
        assert oc.apply(o, "b", h, 5.0) == oc.apply(o, "b", h, 5.0)
        assert len(h) == 1


class Storm(Case):
    def test_same_fingerprint_on_two_beads_inside_the_window_trips(self):
        c = FakeClock()
        fp = oc.fingerprint(Kind.FAULT_BAD_REQUEST, "schema")
        h = [row("a", Kind.FAULT_BAD_REQUEST, fp, c.now())]
        assert lh.storm_trip([], "a", Kind.FAULT_BAD_REQUEST, fp, c.now()) is None
        c.advance(60)
        trip = lh.storm_trip(h, "b", Kind.FAULT_BAD_REQUEST, fp, c.now())
        assert must(trip).beads == ("a", "b")
        assert "clear /cfg/storm/r.json to wake sooner" in lh.banner(must(trip), "/cfg/storm/r.json")
        assert lh.storm_trip(h, "a", Kind.FAULT_BAD_REQUEST, fp, c.now()) is None  # one bead repeating is no storm
        c.advance(1800)
        assert lh.storm_trip(h, "b", Kind.FAULT_BAD_REQUEST, fp, c.now()) is None  # outside the window

    def test_distinct_fingerprints_never_trip_and_non_faults_never_count(self):
        h = [row("a", Kind.FAULT_INFRA, oc.fingerprint(Kind.FAULT_INFRA, "one"), 10.0)]
        assert lh.storm_trip(h, "b", Kind.FAULT_INFRA, oc.fingerprint(Kind.FAULT_INFRA, "two"), 20.0) is None
        for k in (Kind.PAUSE_NETWORK, Kind.PAUSE_KILLED, Kind.PAUSE_LANE, Kind.ASK_DECISION):
            fp = oc.fingerprint(k, "same")
            assert lh.storm_trip([row("a", k, fp, 10.0)], "b", k, fp, 20.0) is None, k

    def test_the_record_is_written_once_and_expires(self):
        p = storm_file.storm_path(mkdtemp(), "repo")
        win = oc.KNOBS["storm_window_s"]
        assert storm_file.write_storm(p, "fp", ("a", "b"), 100.0, 100.0, win)
        assert not storm_file.write_storm(p, "fp", ("a", "b"), 100.0, 150.0, win)
        assert storm_file.read_storm(p, 100.0 + 1800, win) is None
        storm_file.clear_storm(p)
        assert storm_file.write_storm(p, "fp", ("a", "b"), 100.0, 150.0, win)


FIX = Path(__file__).resolve().parents[1] / "fixtures" / "replay"


def rows(name):
    return [json.loads(ln) for ln in (FIX / name).read_text(encoding="utf-8").splitlines() if ln.strip()]


def replay(name, stop_on_trip=True, squeeze=None):
    """Feed a corpus fixture through the close path (fingerprint, apply, storm) one row = one engine call. Returns
    (calls made, banners printed, dispositions). squeeze: spacing in seconds that replaces the real times."""
    clk, history, banners, disps, calls = FakeClock(), [], [], [], 0
    path = storm_file.storm_path(mkdtemp(), "repo")
    for n, r in enumerate(rows(name)):
        clk.t = r["t"] if squeeze is None else 1_000_000.0 + n * squeeze
        calls += 1
        kind = Kind(r["kind"])
        o = oc.make(kind, r["text"])
        disps.append(oc.apply(o, r["bead"], history, clk.now()))
        trip = lh.storm_trip(history, r["bead"], kind, o.fingerprint, clk.now())
        history.append({"bead": r["bead"], "kind": kind.value, "fingerprint": o.fingerprint, "t": clk.now()})
        if trip and storm_file.write_storm(path, trip.fingerprint, trip.beads, trip.t, clk.now(), oc.KNOBS["storm_window_s"], r["text"]):
            banners.append(lh.banner(trip, str(path)))
            if stop_on_trip:
                break
    return calls, banners, disps


class Replay(Case):
    def test_the_53_schema_parks_stop_after_two_calls_with_one_banner(self):
        assert len(rows("schema_park_53.jsonl")) == 53
        calls, banners, disps = replay("schema_park_53.jsonl")
        assert (calls, len(banners)) == (2, 1)
        assert all(not d.ask and d.bd == "open" and d.label == "engine-fault" for d in disps)

    def test_without_the_stop_the_wave_still_writes_one_banner_not_53(self):
        calls, banners, _ = replay("schema_park_53.jsonl", stop_on_trip=False, squeeze=20)
        assert (calls, len(banners)) == (53, 1)

    def test_a_dirty_slot_wave_trips_on_the_second_bead_inside_the_window(self):
        _calls, banners, disps = replay("dirty_slot.jsonl")
        assert len(banners) == 1
        assert "lifesim-jva,lifesim-r0yc" in banners[0]  # the first bead of the file is days earlier: outside the window
        assert all(d.bd == "open" and not d.ask for d in disps)

    def test_the_sigterm_batch_is_paused_never_failed_never_a_storm(self):
        calls, banners, disps = replay("sigterm_batch.jsonl", stop_on_trip=False, squeeze=5)
        assert (calls, banners) == (13, [])
        assert all((d.loop_result, d.bd, d.ask, d.label) == ("paused", "open", False, "") for d in disps)

    def test_the_grok_batch_is_a_lane_pause_the_lane_owner_handles_not_a_run_storm(self):
        calls, banners, disps = replay("grok_prework_batch.jsonl", stop_on_trip=False, squeeze=5)
        assert (calls, banners) == (15, [])
        assert all((d.loop_result, d.ask) == ("paused", False) for d in disps)

    def test_a_network_drop_never_charges_a_cap(self):
        one = rows("network_drop.jsonl")[0]
        o = oc.make(Kind.PAUSE_NETWORK, one["text"])
        history = []
        for i in range(25):  # the same bead dropping 25 times
            d = oc.apply(o, one["bead"], history, 1000.0 + i * 4000)
            assert (d.kind, d.loop_result, d.ask, d.escalated, d.bd) == (Kind.PAUSE_NETWORK, "paused", False, False, "open")
            history.append({"bead": one["bead"], "kind": d.kind.value, "fingerprint": o.fingerprint, "t": 1000.0 + i * 4000})
        assert lh.storm_trip(history, "other-bead", Kind.PAUSE_NETWORK, o.fingerprint, 1000.0 + 25 * 4000) is None

    def test_distinct_failures_do_not_trip(self):
        calls, banners, _ = replay("distinct_faults.jsonl", stop_on_trip=False, squeeze=60)
        assert (calls, banners) == (6, [])
