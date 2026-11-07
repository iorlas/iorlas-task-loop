"""DB-02: full snapshot builds spawn only when their source stamps change."""

import os
import subprocess
import sys
from dataclasses import replace
from unittest.mock import patch

from support.dashlogs import bead
from support.factory_index import ingest

from dashwire import test_dash_api as fixtures
from taskloop.adapters.ident import hostname
from taskloop.app.doctor import profiles
from taskloop.app.launch import dash_ports
from taskloop_dash.index import Indexer
from taskloop_dash.views import snapshot
from tlkernel.env import Env as ProcessEnv


class SnapshotStamps(fixtures.ApiFixture):
    def sources(self):
        gitdir = self.repo / ".git"
        ref = gitdir / "refs" / "heads" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("a" * 40 + "\n")
        (gitdir / "HEAD").write_text("ref: refs/heads/main\n")  # a gitdir without HEAD is not a checkout
        (self.repo / ".task-loop.json").write_text('{"engine":{"base":"main"}}')
        marker = self.repo / ".beads" / "last-touched"
        marker.parent.mkdir(exist_ok=True)
        marker.touch()
        return ref, marker

    def test_full_build_audits_processes_and_invalidates_only_matching_source(self):
        ref, marker = self.sources()
        self.store.put(bead("s-z", f"slot {hostname()} z", labels=["slot"]))
        self.finds = 0
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
                ingest(self.cfg, self.now)
                with Indexer(self.dash.env.config, clock=lambda: self.now, repos=self.dash.records.repos,
                             store_of=self.dash.env.ports.store) as index:
                    index.pass_once()
                return snapshot.build(self.dash.reads.worlds.world())
            finally:
                active[0] = False

        self.store.find = listing
        with patch.object(dash_ports, "store", return_value=self.store), patch.object(profiles, "red_row", side_effect=red_row) as row:
            self.dash.env.ports = dash_ports.ports(ProcessEnv({"HOME": self.tmp.name, "XDG_CONFIG_HOME": self.tmp.name}))
            self.dash.env.ports = replace(self.dash.env.ports, scorecard=lambda *_: None)  # its 60 s TTL reads git
            first = build()
            assert "z" in [s.id for s in first.slots]
            assert events
            assert (self.finds, row.call_count) == (1, 1)
            self.now += 121  # beyond snapshot, profile and fallback listing TTLs
            assert build().slots == first.slots
            assert events == []
            assert (self.finds, row.call_count) == (1, 1)
            self.store.put(bead("s-y", f"slot {hostname()} y", labels=["slot"]))
            stamp = marker.stat().st_mtime_ns + 1
            os.utime(marker, ns=(stamp, stamp))
            changed = build()
            assert "y" in [s.id for s in changed.slots]
            assert events
            assert (self.finds, row.call_count) == (2, 1)
            ref.write_text("b" * 40 + "\n")
            changed = build()
            assert changed.projects[0].profile_error == "RED " + "b" * 40
            assert events
            assert (self.finds, row.call_count) == (2, 2)
