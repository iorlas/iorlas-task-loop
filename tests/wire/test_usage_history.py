"""The lane usage history (append on each filed snapshot, prune by age), the forecast on synthetic series, the lane-card state map,
and the Snapshot's lanes decoding strictly."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.narrow import must

from taskloop.app.wire import lanes
from taskloop.contracts import wire
from taskloop.contracts.dash import Snapshot
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import LaneStatus, StatusSnapshot, WindowStatus
from taskloop.contracts.stores import UsageHistory
from taskloop.contracts.usage import USAGE_KEEP_S, UsageRow, forecast, rows_of
from taskloop_dash.views import snapshot
from taskloop_dash.views.lanecards import STATUS_MAX_AGE, lane_cards
from taskloop_dash.views.world import World

T = 1_800_000_000.0
H = 3600.0


def series(points, reset=T + 5 * H, lane="A", window="w"):
    return [UsageRow(at=T + h * H, lane=lane, window=window, used_pct=u, resets_at=r if r is not None else reset) for h, u, r in points]


def snap(at, state="ready", five=None, week=None, used=10.0, reset=T + 5 * H, out=False, out_until=None):
    return StatusSnapshot(at=at, lanes=[LaneStatus(
        id="A", label="Claude", family="claude", kind="subscription", model="m", state=state, five=five, week=week, unlock_at=at + 600,
        out=out, out_until=out_until,
        windows=[WindowStatus(name="whatever", used_pct=used, resets_at=reset), WindowStatus(name="unknown")])])


class History(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(tmp.name)
        self.h = UsageHistory(self.cfg)

    def test_a_snapshot_appends_one_row_per_window_that_reports_a_use(self):
        self.h.record(snap(T))
        self.h.record(snap(T + 60, used=12.0))
        self.assertEqual([(r.at, r.window, r.used_pct, r.resets_at) for r in self.h.rows()],
                         [(T, "whatever", 10.0, T + 5 * H), (T + 60, "whatever", 12.0, T + 5 * H)])
        self.assertEqual(rows_of(snap(T))[0].lane, "A")

    def test_prune_drops_rows_older_than_the_keep_age_and_keeps_the_rest_byte_for_byte(self):
        old = T - USAGE_KEEP_S - 1
        for at in (old, T - USAGE_KEEP_S, T):
            self.h.record(snap(at))
        before = self.cfg.usage_history().read_bytes().splitlines(keepends=True)
        self.assertEqual(self.h.prune(T), 1)
        self.assertEqual(self.cfg.usage_history().read_bytes(), b"".join(before[1:]))
        self.assertEqual(self.h.prune(T), 0)
        self.h.record(snap(T + 1))
        self.assertEqual(len(self.h.rows()), 3)

    def test_prune_without_a_file_is_a_no_op(self):
        self.assertEqual(self.h.prune(T), 0)

    def test_filing_an_answer_records_and_prunes(self):
        UsageHistory(self.cfg).record(snap(T - USAGE_KEEP_S - 5))
        window = {"name": "x", "used_pct": 3, "resets_at": T + H}
        answer = json.dumps({"ts": T, "lanes": {}, "cockpit": {"lanes": [{"id": "A", "state": "ready", "windows": [window]}]}})
        self.assertIsNone(lanes.file_answer(answer, self.cfg))
        self.assertEqual([(r.at, r.used_pct) for r in self.h.rows()], [(T, 3.0)])


class Forecast(unittest.TestCase):
    def test_flat_use_projects_flat(self):
        self.assertAlmostEqual(must(forecast(series([(0, 20, None), (1, 20, None), (2, 20, None)]), T + 2 * H)), 20.0)

    def test_rising_use_projects_the_line_to_the_reset(self):
        rows = series([(0, 10, None), (1, 20, None), (2, 30, None)])  # 10 pct an hour, reset at hour 5
        self.assertAlmostEqual(must(forecast(rows, T + 2 * H)), 60.0)

    def test_the_projection_stops_at_100(self):
        self.assertEqual(forecast(series([(0, 40, None), (1, 70, None), (2, 90, None)]), T + 2 * H), 100.0)

    def test_a_reset_mid_series_leaves_only_the_new_window(self):
        old = series([(0, 80, T + H), (0.5, 95, T + H)])
        new = series([(1.2, 2, T + 6 * H), (2.2, 4, T + 6 * H)])  # 2 pct an hour, reset at hour 6
        self.assertAlmostEqual(must(forecast(old + new, T + 2.2 * H)), 4 + 2 * 3.8)
        self.assertIsNone(forecast(old + new[:1], T + 1.2 * H))  # one row since the reset

    def test_a_fall_in_use_without_a_new_reset_time_is_a_reset_too(self):
        rows = series([(0, 50, None), (1, 60, None), (2, 5, None), (3, 10, None)])
        self.assertAlmostEqual(must(forecast(rows, T + 3 * H)), 10 + 5 * 2)

    def test_too_few_rows_none(self):
        self.assertIsNone(forecast([], T))
        self.assertIsNone(forecast(series([(0, 20, None)]), T))

    def test_no_reset_time_or_a_reset_past_or_one_instant_is_none(self):
        rows = series([(0, 10, None), (1, 20, None)])
        self.assertIsNone(forecast([UsageRow(at=r.at, lane="A", window="w", used_pct=r.used_pct) for r in rows], T + H))
        self.assertIsNone(forecast(rows, T + 5 * H))
        self.assertIsNone(forecast(series([(1, 10, None), (1, 20, None)]), T + H))

    def test_only_the_last_twelve_rows_of_the_window_count(self):
        rows = series([(i, 0 if i == 0 else 50, None) for i in range(13)], reset=T + 14 * H)
        self.assertAlmostEqual(must(forecast(rows, T + 12 * H)), 50.0)  # hours 1..12 are flat: the hour-0 row is outside the fit


class Cards(unittest.TestCase):
    def test_delegate_states_map_to_card_states_and_locked_needs_out(self):
        for delegate, card in (("ready", "ok"), ("slow", "watch"), ("unknown", "watch"), ("resting", "watch"),
                               ("logged_out", "watch"), ("spend", "watch"), ("off", "watch"), ("new", "watch")):
            with self.subTest(delegate):
                self.assertEqual(lane_cards(snap(T, state=delegate), T + 60)[0].state, card)

    def test_out_locks_the_card_until_out_until(self):
        for delegate in ("ready", "resting", "new"):
            c = lane_cards(snap(T, state=delegate, out=True, out_until=T + 900), T + 60)[0]
            self.assertEqual((c.state, c.locked_until), ("locked", T + 900))
        self.assertIsNone(lane_cards(snap(T, out=True), T + 60)[0].locked_until)
        self.assertIsNone(lane_cards(snap(T, state="resting", out_until=T + 900), T + 60)[0].locked_until)

    def test_an_old_snapshot_greys_every_card_and_keeps_its_age(self):
        c = lane_cards(snap(T, five=40.0), T + STATUS_MAX_AGE + 1)[0]
        self.assertEqual((c.state, c.status_t, c.window_pct), ("stale", T, 40.0))
        self.assertEqual(lane_cards(snap(T), T + STATUS_MAX_AGE)[0].state, "ok")
        locked = lane_cards(snap(T, out=True, out_until=T + 9000), T + STATUS_MAX_AGE + 1)[0]
        self.assertEqual((locked.state, locked.locked_until), ("stale", None))

    def test_only_the_typed_windows_fill_and_the_rest_stays_unset(self):
        c = lane_cards(snap(T, state="resting", five=41.0, week=6.0, used=99.0, out=True, out_until=T + 600), T + 1)[0]
        self.assertEqual((c.window_pct, c.week_pct, c.locked_until, c.model), (41.0, 6.0, T + 600, "m"))
        self.assertEqual((c.name, c.plan), ("claude", "subscription"))
        self.assertEqual((c.forecast_pct, c.resets_at, c.forecast, c.slots), (None, None, "", []))
        self.assertIsNone(lane_cards(snap(T, state="ready"), T + 1)[0].locked_until)
        self.assertEqual(lane_cards(None, T), [])

    def test_the_snapshot_carries_the_cards_and_decodes_strictly(self):
        w = World(now=T + 60, host="h", version="v", projects=[], runs={}, asks={}, status=snap(T, five=41.0))
        built = snapshot.build(w)
        self.assertEqual([c.window_pct for c in built.lanes], [41.0])
        self.assertEqual(wire.load(Snapshot, wire.dump(built)), built)
        bad = wire.dump(built)
        bad["lanes"][0]["window_pct"] = "41"
        with self.assertRaises(ValueError):
            wire.load(Snapshot, bad)
        bad["lanes"][0] = {**wire.dump(built)["lanes"][0], "extra": 1}
        with self.assertRaises(ValueError):
            wire.load(Snapshot, bad)


if __name__ == "__main__":
    unittest.main()
