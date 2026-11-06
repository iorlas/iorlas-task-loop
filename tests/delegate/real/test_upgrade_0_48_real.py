"""An install from before 0.48 (CLAUDE_CREDIT lane, codex_login_pid) must upgrade with no hand edits"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from delegate.app import doctor, env
from delegate.contracts.stores import StateStore, StateUnreadable
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import run_support as T
from test_route import route

FIX = Path(__file__).resolve().parent.parent / "fixtures"
ROUTE_PY = Path(str(route.__file__))


class Upgrade(T.RunBase):
    def load_state(self, name="state.json"):
        path = Path(self.tmp.name, name)
        shutil.copy(FIX / "state_pre_0_48.json", path)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            doc = StateStore(path).load()
        return doc, err.getvalue().splitlines(), path

    @real_proc("delegate: a worker, git or CLI process")
    def test_state_drops_retired_keys_and_lane_entries_keeps_live_ones(self):
        before = (FIX / "state_pre_0_48.json").read_bytes()
        doc, warned, path = self.load_state()
        assert sorted(doc.out) == ["OPENAI_SUBSCRIPTION"]
        assert doc.out["OPENAI_SUBSCRIPTION"].source == "vendor"
        assert list(doc.holds) == ["h1"]
        assert doc.holds["h1"].reason == "keep for me"
        assert doc.leases["r-live"].pid == 4242
        assert list(doc.auth) == ["OPENAI_SUBSCRIPTION"]
        assert len(warned) == 2, warned
        assert any("'codex_login_pid'" in w for w in warned)
        assert any("'out.CLAUDE_CREDIT'" in w for w in warned)
        assert all(str(path) in w for w in warned)
        assert path.read_bytes() == before  # a load alone rewrites nothing

    @real_proc("delegate: a worker, git or CLI process")
    def test_state_retired_lane_in_holds_leases_and_refs_goes_too(self):
        path = Path(self.tmp.name, "state.json")
        d = json.loads((FIX / "state_pre_0_48.json").read_text())
        d["holds"]["h2"] = {**d["holds"]["h1"], "id": "h2", "lane": "CLAUDE_CREDIT"}
        d["leases"]["r-old"] = {**d["leases"]["r-live"], "lane": "CLAUDE_CREDIT"}
        d["refs"]["abc"] = {"lane": "CLAUDE_CREDIT", "model": "m", "effort": "e", "mode": "x"}
        path.write_text(json.dumps(d))
        with contextlib.redirect_stderr(io.StringIO()):
            doc = StateStore(path).load()
        assert (list(doc.holds), list(doc.leases), list(doc.refs)) == (["h1"], ["r-live"], [])

    @real_proc("delegate: a worker, git or CLI process")
    def test_state_unknown_key_that_is_not_retired_is_refused_and_left_untouched(self):
        path = Path(self.tmp.name, "state.json")
        d = json.loads((FIX / "state_pre_0_48.json").read_text())
        d["mystery"] = 1
        path.write_text(json.dumps(d))
        before = path.read_bytes()
        with pytest.raises(StateUnreadable, match=r"state\.json\.old"):
            StateStore(path).load()
        assert path.read_bytes() == before

    @real_proc("delegate: a worker, git or CLI process")
    def test_config_with_retired_keys_warns_naming_file_safe_to_delete_and_is_untouched(self):
        cfg = Path(self.tmp.name, "config.json")
        shutil.copy(FIX / "config_pre_0_45.json", cfg)
        before = cfg.read_bytes()
        err = io.StringIO()
        env._RETIRED_WARNED.clear()
        with contextlib.redirect_stderr(err):
            env.load_routing()
        w = [ln for ln in err.getvalue().splitlines() if "'credit'" in ln]
        assert len(w) == 1
        assert str(cfg) in w[0]
        assert "safe to delete" in w[0]
        assert cfg.read_bytes() == before
        assert env.profile_lanes()["CLAUDE_CREDIT"] == "declined"  # a retired lane in the profile is just ignored

    @real_proc("delegate: a worker, git or CLI process")
    def test_leftovers_are_listed_by_doctor_and_never_deleted(self):
        cfg = env.load_routing()
        d = Path(self.tmp.name)
        assert [n for n in doctor.notes(cfg) if n["id"].startswith("unused")] == []
        (d / "claude-credit.key").write_text("sk-secret")
        (d / "ledger.jsonl").write_text("{}\n")
        os.environ["CLAUDE_CREDIT_WORKER_KEY"] = "sk-secret"
        self.addCleanup(os.environ.pop, "CLAUDE_CREDIT_WORKER_KEY", None)
        notes = [n for n in doctor.notes(cfg) if n["id"].startswith("unused")]
        assert sorted(n["id"] for n in notes) == ["unused_env", "unused_file", "unused_file"]
        assert all("unused, safe to" in n["say"] for n in notes)
        assert (d / "claude-credit.key").exists() and (d / "ledger.jsonl").exists()
        p = subprocess.run(
            [sys.executable, str(ROUTE_PY), "doctor", "--json"], env=os.environ, capture_output=True, text=True, timeout=60, check=False
        )
        assert len([n for n in json.loads(p.stdout)["notes"] if n["id"].startswith("unused")]) == 3
        p = subprocess.run(
            [sys.executable, str(ROUTE_PY), "doctor"], env=os.environ, capture_output=True, text=True, timeout=60, check=False
        )
        assert len([ln for ln in p.stdout.splitlines() if "unused, safe to" in ln]) == 3
        assert (d / "claude-credit.key").read_text() == "sk-secret"

    @real_proc("delegate: a worker, git or CLI process")
    @pytest.mark.skipif(os.name == "nt", reason="fake codex/claude are shell scripts")
    def test_run_ignores_leftovers_and_keeps_live_state(self):
        d = Path(self.tmp.name)
        shutil.copy(FIX / "state_pre_0_48.json", d / "state.json")
        (d / "claude-credit.key").write_text("sk-secret")
        (d / "ledger.jsonl").write_text("{}\n")
        os.environ.update(FAKE_MODE="ok", CLAUDE_CREDIT_WORKER_KEY="sk-secret")
        self.addCleanup(os.environ.pop, "CLAUDE_CREDIT_WORKER_KEY", None)
        p = subprocess.run(
            [sys.executable, str(ROUTE_PY), "run", "worker", "--cwd", self.repo, "--unattended", "--timeout", "30"],
            input="do the thing\nthe brief",
            env=os.environ,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert p.returncode == 0, p.stderr
        assert "CLAUDE_CREDIT" not in p.stderr.replace("'out.CLAUDE_CREDIT'", "")
        assert "sk-secret" not in p.stdout + p.stderr
        st = json.loads((d / "state.json").read_text())
        assert "codex_login_pid" not in st
        assert "h1" in st["holds"]  # the live lane's hold survived the run's own save
        assert (d / "claude-credit.key").exists() and (d / "ledger.jsonl").exists()
