"""Poll latency, build concurrency, and append-only engine-log regression tests."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from support.hostname import hostname

from dashwire import test_dash_api as fixtures
from tldash.testing import bead, seed_beads
from tlkernel.ids import loop_key
from tltestkit.narrow import must


class FastReads(fixtures.ApiFixture):
    def test_missing_stamp_retains_the_thirty_second_fallback(self):
        worlds = self.dash.reads.worlds
        with patch.object(self.dash.env.ports, "profile_error", side_effect=["", "RED"]) as row:
            assert worlds.world().projects[0].profile_error == ""
            self.now += 29
            assert worlds.world().projects[0].profile_error == ""
            assert row.call_count == 1
            self.now += 2
            assert worlds.world().projects[0].profile_error == "RED"
            assert row.call_count == 2

    def test_cached_listing_supplies_floor_slots_and_profile_is_cached(self):
        self.store.put(bead("s-z", f"slot {hostname()} z", labels=["slot"]))
        seed_beads(self.cfg, self.repo, self.store.beads.values(), self.now)
        with patch.object(self.dash.env.ports, "profile_error", return_value="") as profile:
            snap = self.dash.reads.snapshot()
            assert "z" in [s.id for s in snap.slots]
            self.dash.reads.worlds.world()
            assert profile.call_count == 1
            assert self.finds == 1
            with patch("subprocess.Popen", side_effect=AssertionError("warm poll spawned")):
                assert self.dash.reads.snapshot() is snap
                self.now += 4
                assert self.dash.reads.snapshot() is snap
                self.dash.reads.wait()
            assert self.finds == 1
            assert profile.call_count == 1

    def test_concurrent_cost_requests_share_one_build(self):
        entered, release = threading.Event(), threading.Event()
        original = self.dash.reads.worlds.world

        def build():
            entered.set()
            release.wait(2)
            return original()

        with patch.object(self.dash.reads.worlds, "world", side_effect=build) as world, ThreadPoolExecutor(8) as pool:
            futures = [pool.submit(self.dash.reads.cost, "24h", 0, "") for _ in range(8)]
            try:
                assert entered.wait(1)
            finally:
                release.set()
            pages = [f.result(2) for f in futures]
            assert world.call_count == 1
            assert all(p is pages[0] for p in pages)

    def test_first_concurrent_requests_share_one_build(self):
        entered, release = threading.Event(), threading.Event()
        original = self.dash.reads.worlds.world

        def build():
            entered.set()
            release.wait(2)
            return original()

        with patch.object(self.dash.reads.worlds, "world", side_effect=build) as world, ThreadPoolExecutor(8) as pool:
            futures = [pool.submit(self.dash.reads.snapshot) for _ in range(8)]
            try:
                assert entered.wait(1)
            finally:
                release.set()
            results = [f.result(2) for f in futures]
            assert world.call_count == 1
            assert all(r is results[0] for r in results)

    def test_stale_poll_returns_last_build_while_one_refresh_runs(self):
        first = self.dash.reads.snapshot()
        self.now += 4
        entered, release = threading.Event(), threading.Event()
        original = self.dash.reads.worlds.world

        def build():
            entered.set()
            release.wait(2)
            return original()

        with patch.object(self.dash.reads.worlds, "world", side_effect=build) as world:
            try:
                assert self.dash.reads.snapshot() is first
                assert entered.wait(1)
                assert all(self.dash.reads.snapshot() is first for _ in range(8))
                assert world.call_count == 1
            finally:
                release.set()
                self.dash.reads.cache.wait()
        assert self.dash.reads.snapshot().t == self.now

    def test_drawer_reuses_world_and_single_flight(self):
        self.dash.reads.snapshot()
        with patch.object(self.dash.reads.worlds, "world", side_effect=AssertionError("whole world rebuilt")):
            detail = self.dash.reads.bead(loop_key(self.repo), "b-1")
            assert must(detail).card.id == "b-1"
            with patch.object(self.dash.reads.worlds, "comments", side_effect=AssertionError("drawer rebuilt")):
                assert self.dash.reads.bead(loop_key(self.repo), "b-1") is detail
            self.now += 4
            assert self.dash.reads.bead(loop_key(self.repo), "b-1") is detail
            self.dash.reads.wait()

    def test_drawer_concurrency_and_stale_refresh_share_one_build(self):
        self.dash.reads.snapshot()
        entered, release = threading.Event(), threading.Event()
        original = self.dash.reads.worlds.comments

        def comments(*args):
            entered.set()
            release.wait(2)
            return original(*args)

        with patch.object(self.dash.reads.worlds, "comments", side_effect=comments) as read, ThreadPoolExecutor(8) as pool:
            futures = [pool.submit(self.dash.reads.bead, loop_key(self.repo), "b-1") for _ in range(8)]
            try:
                assert entered.wait(1)
            finally:
                release.set()
            results = [f.result(2) for f in futures]
            assert read.call_count == 1
            assert all(r is results[0] for r in results)
            entered.clear()
            release.clear()
            self.now += 4
            try:
                assert self.dash.reads.bead(loop_key(self.repo), "b-1") is results[0]
                assert entered.wait(1)
                assert all(self.dash.reads.bead(loop_key(self.repo), "b-1") is results[0] for _ in range(8))
                assert read.call_count == 2
            finally:
                release.set()
                self.dash.reads.wait()
