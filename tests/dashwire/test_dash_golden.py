"""The dashboard's answers for one recorded state: a run per way a run can end (the close each Kind writes), read through the API
(snapshot, bead drawer). The golden file is the answer as the page reads it; it changes only when a
field was wrong. `GOLDEN_WRITE=1 uv run pytest tests/dashwire/test_dash_golden.py` rewrites it."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.dashlogs import RunScript, T, bead
from support.factory_index import ingest, seed_beads
from support.fakes import FakeBeadStore

from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports
from taskloop_dash.views.snapshot import version_of
from tlkernel import wire
from tlkernel.dash import BeadDetail, Snapshot
from tlkernel.ids import loop_key
from tltestkit.repos import write_repos

GOLDEN = Path(__file__).resolve().parents[1] / "dash" / "golden" / "closes.json"
NOW = T + 36_000
# (name, close outcome word, why_code, why): what the closer writes for each Kind (app/run/trace.WHY_CODE, outcome.RunOutcome.word)
CLOSES = [
    ("landed", "landed", None, ""),
    ("done", "done", None, ""),
    ("ask-decision", "blocked", "owner_decision", "owner decision needed: old format or new?"),
    ("ask-verify", "blocked", "owner_decision", "verify: before land, the workers could not check: the look (other)"),
    ("ask-stuck", "blocked", "stuck", "stage 1 stuck after 3 rounds and 1 re-plan(s)"),
    ("ask-budget", "blocked", "over_budget", "over budget: write 61 min of 60"),
    ("ask-ticket", "blocked", "ticket", "ticket: the bead has no acceptance criteria"),
    ("wait-ask", "blocked", "needs_human", "waiting: for the owner's answer to ask g-1 (decision): which?"),
    ("pause-lane", "blocked", "lane_out", "paused: no lane for the write step (CODEX_SUBSCRIPTION out until 14:00)"),
    ("pause-network", "blocked", "network", "paused: no network for the land push after 90 s; the branch is kept"),
    ("pause-killed", "failed", "stopped_by_coordinator", "failed: stopped (SIGTERM)"),
    ("owner-park", "blocked", "paused", "parked: by the owner (the branch and the checkpoint are kept; release the hold to go on)"),
    ("fault-denied", "failed", "needs_human", "needs a human: the write step was denied rm and gave no answer"),
    ("fault-land", "failed", "check_before_land", "failed: the land gate is red on main"),
    ("fault-infra", "failed", "failed", "failed: infrastructure: no slot"),
    ("fault-engine", "failed", "failed", "failed: engine error KeyError: 'x'"),
]


class Golden(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        repo = root / "lifesim"
        repo.mkdir()
        self.project = loop_key(repo)
        self.repo = repo
        self.cfg = root / "cfg"
        self.cfg.mkdir()
        write_repos(self.cfg / "repos.json", repo)
        self.store = FakeBeadStore()
        self.paths = {}
        for i, (name, outcome, code, why) in enumerate(CLOSES):
            bid = f"g-{i + 1}"
            self.store.put(bead(bid, name))
            run = RunScript(bid, slot="a", at=i * 100).step("plan", 30, 1000, "OC Go").step("write", 40, 2000, text="write 1")
            run.step("close", 1, text=f"close: {outcome}", end=False).close(outcome, code, why)
            run.add("step_end", id=f"n{run.n}", step="close", outcome="done", exec_seconds=1)
            run.write(self.cfg, repo=str(self.repo))
            self.paths[name] = str(self.cfg / "engine" / f"{run.name}.jsonl")
        ports = Ports(store=lambda r: self.store)
        seed_beads(self.cfg, self.repo, self.store.beads.values(), NOW)
        ingest(self.cfg, NOW)
        self.dash = Dash(Env(config=self.cfg, home=root, ports=ports, clock=lambda: NOW, version="v-test", host="devbox"))

    def teardown_method(self):
        self.tmp.cleanup()

    def answers(self):
        out = {"snapshot": json.loads(self.dash.reads.get("/api/snapshot", {}, None)[1])}
        out["beads"] = {n: json.loads(self.dash.reads.get("/api/bead", {"project": self.project, "id": f"g-{i + 1}"}, None)[1])
                        for i, (n, *_) in enumerate(CLOSES)}
        # Normalize temporary-directory keys before hashing the golden response.
        def stable(value):
            if isinstance(value, dict):
                return {k: stable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [stable(v) for v in value]
            return loop_key("/repos/lifesim") if value == self.project else value
        out = stable(out)
        snap = wire.load(Snapshot, out["snapshot"])
        out["snapshot"]["version"] = version_of(snap)
        for body in out["beads"].values():
            body["version"] = version_of(wire.load(BeadDetail, body))
        return json.loads(json.dumps(out, sort_keys=True))

    def test_the_answers_for_the_recorded_state_are_the_golden(self):
        got = self.answers()
        if os.environ.get("GOLDEN_WRITE"):
            GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        # Fill newly added optional fields from the contract before comparing the recorded state and its hash.
        snap = wire.load(Snapshot, expected["snapshot"])
        expected["snapshot"] = wire.dump(snap.replace(version=version_of(snap)))
        for name, body in expected["beads"].items():
            detail = wire.load(BeadDetail, body)
            expected["beads"][name] = wire.dump(detail.replace(version=version_of(detail)))
        assert got == expected

    def test_the_golden_is_the_same_under_different_system_hostnames(self):
        for hostname in ("devbox", "dtomilin-mWG"):
            with self.subTest(hostname=hostname), patch("socket.gethostname", return_value=hostname) as system_host:
                # Fresh caches ensure each host is tested through all readers.
                self.dash = Dash(Env(config=self.cfg, home=self.repo.parent, ports=Ports(store=lambda _: self.store),
                                     clock=lambda: NOW, version="v-test", host="devbox"))
                self.test_the_answers_for_the_recorded_state_are_the_golden()
                assert self.dash.reads.worlds.slot_source(str(self.repo)).host == "devbox"
                system_host.assert_not_called()
