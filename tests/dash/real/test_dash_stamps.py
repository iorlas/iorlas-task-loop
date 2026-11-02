"""DB-02: full snapshot builds spawn only when their source stamps change."""

import os
import socket
import subprocess
import sys
from unittest.mock import patch

from support.dashlogs import bead

from dash import test_dash_api as fixtures
from taskloop.app.doctor import profiles
from taskloop.app.launch import dash_ports
from taskloop.contracts.env import Env as ProcessEnv
from taskloop_dash.views import snapshot


class SnapshotStamps(fixtures.ApiFixture):
    def sources(self):
        gitdir = self.repo / ".git"
        ref = gitdir / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("a" * 40 + "\n")
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"main"}}')
        marker = self.repo / ".beads" / "last-touched"
        marker.parent.mkdir()
        marker.touch()
        return ref, marker

    def test_full_build_audits_processes_and_invalidates_only_matching_source(self):
        ref, marker = self.sources()
        self.store.put(bead("s-z", f"slot {socket.gethostname()} z", labels=["slot"]))
        original = self.store.find

        def spawn():
            subprocess.run([sys.executable, "-c", "pass"], check=True)

        def listing(query):
            spawn()
            return original(query)

        def red_row(*args):
            spawn()
            return "RED " + ref.read_text().strip()

        active, events = [False], []

        def audit(event, args):
            if active[0] and (event in {"subprocess.Popen", "os.posix_spawn", "os.fork"} or event.startswith("os.exec")):
                events.append(event)

        sys.addaudithook(audit)

        def build():
            events.clear()
            active[0] = True
            try:
                return snapshot.build(self.dash.reads.worlds.world())
            finally:
                active[0] = False

        self.store.find = listing
        with patch.object(dash_ports, "store", return_value=self.store), patch.object(profiles, "red_row", side_effect=red_row) as row:
            self.dash.env.ports = dash_ports.ports(ProcessEnv({"HOME": self.tmp.name, "XDG_CONFIG_HOME": self.tmp.name}))
            first = build()
            self.assertIn("z", [s.id for s in first.slots])
            self.assertTrue(events)
            self.assertEqual((self.finds, row.call_count), (1, 1))
            self.now += 121  # beyond snapshot, profile, shared listing, and fallback listing TTLs
            self.assertEqual(build().slots, first.slots)
            self.assertEqual(events, [])
            self.assertEqual((self.finds, row.call_count), (1, 1))
            self.store.put(bead("s-y", f"slot {socket.gethostname()} y", labels=["slot"]))
            stamp = marker.stat().st_mtime_ns + 1
            os.utime(marker, ns=(stamp, stamp))
            changed = build()
            self.assertIn("y", [s.id for s in changed.slots])
            self.assertTrue(events)
            self.assertEqual((self.finds, row.call_count), (2, 1))
            ref.write_text("b" * 40 + "\n")
            changed = build()
            self.assertEqual(changed.projects[0].profile_error, "RED " + "b" * 40)
            self.assertTrue(events)
            self.assertEqual((self.finds, row.call_count), (2, 2))
