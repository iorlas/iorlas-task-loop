"""Poll latency, build concurrency, and append-only engine-log regression tests."""

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from support.dashlogs import bead
from support.narrow import must

from dash import test_dash_api as fixtures
from taskloop.contracts.ids import loop_key
from taskloop_dash import jsonl
from taskloop_dash.views.runfacts import fold


class FastReads(fixtures.ApiFixture):
    def test_missing_stamp_retains_the_thirty_second_fallback(self):
        worlds = self.dash.reads.worlds
        with patch.object(self.dash.env.ports, "profile_error", side_effect=["", "RED"]) as row:
            self.assertEqual(worlds.world().projects[0].profile_error, "")
            self.now += 29
            self.assertEqual(worlds.world().projects[0].profile_error, "")
            self.assertEqual(row.call_count, 1)
            self.now += 2
            self.assertEqual(worlds.world().projects[0].profile_error, "RED")
            self.assertEqual(row.call_count, 2)

    def test_cached_listing_supplies_floor_slots_and_profile_is_cached(self):
        self.store.put(bead("s-z", f"slot {socket.gethostname()} z", labels=["slot"]))
        with patch.object(self.dash.env.ports, "profile_error", return_value="") as profile:
            snap = self.dash.reads.snapshot()
            self.assertIn("z", [s.id for s in snap.slots])
            self.dash.reads.worlds.world()
            self.assertEqual(profile.call_count, 1)
            self.assertEqual(self.finds, 1)
            with patch("subprocess.Popen", side_effect=AssertionError("warm poll spawned")):
                self.assertIs(self.dash.reads.snapshot(), snap)
                self.now += 4
                self.assertIs(self.dash.reads.snapshot(), snap)
                self.dash.reads.wait()
            self.assertEqual(self.finds, 1)
            self.assertEqual(profile.call_count, 1)

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
                self.assertTrue(entered.wait(1))
            finally:
                release.set()
            results = [f.result(2) for f in futures]
            self.assertEqual(world.call_count, 1)
            self.assertTrue(all(r is results[0] for r in results))

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
                self.assertIs(self.dash.reads.snapshot(), first)
                self.assertTrue(entered.wait(1))
                self.assertTrue(all(self.dash.reads.snapshot() is first for _ in range(8)))
                self.assertEqual(world.call_count, 1)
            finally:
                release.set()
                self.dash.reads.cache.wait()
        self.assertEqual(self.dash.reads.snapshot().t, self.now)

    def test_drawer_reuses_world_and_single_flight(self):
        self.dash.reads.snapshot()
        with patch.object(self.dash.reads.worlds, "world", side_effect=AssertionError("whole world rebuilt")):
            detail = self.dash.reads.bead(loop_key(self.repo), "b-1")
            self.assertEqual(must(detail).card.id, "b-1")
            with patch.object(self.dash.reads.worlds, "comments", side_effect=AssertionError("drawer rebuilt")):
                self.assertIs(self.dash.reads.bead(loop_key(self.repo), "b-1"), detail)
            self.now += 4
            self.assertIs(self.dash.reads.bead(loop_key(self.repo), "b-1"), detail)
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
                self.assertTrue(entered.wait(1))
            finally:
                release.set()
            results = [f.result(2) for f in futures]
            self.assertEqual(read.call_count, 1)
            self.assertTrue(all(r is results[0] for r in results))
            entered.clear()
            release.clear()
            self.now += 4
            try:
                self.assertIs(self.dash.reads.bead(loop_key(self.repo), "b-1"), results[0])
                self.assertTrue(entered.wait(1))
                self.assertTrue(all(self.dash.reads.bead(loop_key(self.repo), "b-1") is results[0] for _ in range(8)))
                self.assertEqual(read.call_count, 2)
            finally:
                release.set()
                self.dash.reads.wait()


class IncrementalLogs(fixtures.ApiFixture):
    def test_cross_poll_call_pair_folds_only_appended_records(self):
        reader = self.dash.runlogs
        bundle = must(self.dash.records.locator.get("b-1-20261015-100000"))
        reader.typed_run(bundle, self.now)
        start = {"v": 3, "kind": "call_start", "t": self.now, "id": "late", "n": 2,
                 "step": "write", "node": "n2", "role": "writer"}
        end = {"v": 3, "kind": "call_end", "t": self.now + 2, "id": "late", "status": "ok",
               "tokens": {"in": 10, "cached": 2, "out": 3}, "exit": 0}
        with patch("taskloop_dash.readers.runlogs.fold", wraps=fold) as append:
            for row in (start, end):
                with bundle.log.open("ab") as file:
                    file.write(json.dumps(row).encode() + b"\n")
                made = reader.typed_run(bundle, self.now)
                self.assertEqual([r.kind for r in append.call_args.args[1]], [row["kind"]])
        self.assertEqual((made.calls[-1].t, made.calls[-1].tokens, made.exit_code), (self.now, 11, 0))
        self.assertEqual(reader.runs[str(bundle.log)].state.open_calls, ())

    def test_snapshot_omits_rows_and_drawer_loads_only_its_bead(self):
        world, _ = self.dash.reads.built()
        self.assertTrue(world.runs)
        self.assertTrue(all(r.records == () for runs in world.runs.values() for r in runs))
        with patch.object(jsonl, "records", wraps=jsonl.records) as read:
            detail = must(self.dash.reads.bead(loop_key(self.repo), "b-1"))
        engine_paths = [c.args[0] for c in read.call_args_list if "/engine/" in c.args[0]]
        self.assertEqual(engine_paths, [str(self.cfg / "engine" / "b-1-20261015-100000.jsonl")])
        self.assertTrue(any(role.role == "writer" for p in detail.passes for stage in p.logs for role in stage.roles))
        self.assertTrue(all(r.records == () for runs in world.runs.values() for r in runs))

    def test_append_partial_rotation_and_truncation(self):
        reader = self.dash.reads.worlds.runlogs
        bundle = must(self.dash.records.locator.get("b-1-20261015-100000"))
        initial = bundle.log.read_bytes()
        with patch.object(jsonl, "parse", wraps=jsonl.parse) as parse:
            first = reader.typed_run(bundle, self.now)
            self.assertEqual(parse.call_count, len(initial.splitlines()))
            parse.reset_mock()
            record = json.dumps({"v": 3, "kind": "beat", "t": self.now}).encode()
            with bundle.log.open("ab") as file:
                file.write(record[:20])
            self.assertEqual(reader.typed_run(bundle, self.now), first)
            self.assertEqual(parse.call_count, 0)
            with bundle.log.open("ab") as file:
                file.write(record[20:] + b"\n")
            reader.typed_run(bundle, self.now)
            self.assertEqual([c.args[0] for c in parse.call_args_list], [record])
            parse.reset_mock()
            replacement = bundle.log.with_suffix(".replacement")
            replacement.write_bytes(initial)
            replacement.replace(bundle.log)
            self.assertEqual(reader.typed_run(bundle, self.now), first)
            self.assertEqual(parse.call_count, len(initial.splitlines()))
            parse.reset_mock()
            bundle.log.write_bytes(initial.splitlines(keepends=True)[0])
            self.assertEqual(reader.typed_run(bundle, self.now).records, ())
            self.assertEqual(reader.typed_run(bundle, self.now).spans, ())
            self.assertEqual(parse.call_count, 1)

    def test_only_last_beat_is_retained(self):
        reader = self.dash.reads.worlds.runlogs
        bundle = must(self.dash.records.locator.get("b-1-20261015-100000"))
        with bundle.log.open("ab") as file:
            for t in range(10):
                file.write(json.dumps({"v": 3, "kind": "beat", "t": self.now + t}).encode() + b"\n")
        reader.typed_run(bundle, self.now)
        tail = reader.runs[str(bundle.log)]
        self.assertEqual(must(tail.beat).t, self.now + 9)
        self.assertFalse(hasattr(tail, "records"))
