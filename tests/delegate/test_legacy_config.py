"""A real pre-0.45 config.json (tests/fixtures/config_pre_0_45.json, retired keys and all) must still drive `route.py run`."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from delegate.app import env
from delegate.contracts.routing import RETIRED_SETTINGS, split_retired
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import run_support as T
from test_route import route

FIXTURE = Path(__file__).parent / "fixtures" / "config_pre_0_45.json"
ROUTE_PY = Path(str(route.__file__))


# Each case starts several python children that import the whole delegate package (seconds apiece on a busy host), over the 15 s default.
LIMIT_S = 60


class LegacyConfig:
    tmp: tempfile.TemporaryDirectory[str]
    base: Path
    repo: str
    FAKE_CODEX, FAKE_CLAUDE = T.RunBase.FAKE_CODEX, T.RunBase.FAKE_CLAUDE
    setup_method, teardown_method, fresh_usage = T.RunBase.setup_method, T.RunBase.teardown_method, T.RunBase.fresh_usage

    def put_config(self, extra=None):
        cfg = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cfg.update(extra or {})
        Path(self.tmp.name, "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def run_py(self, *args):
        os.environ["FAKE_MODE"] = "ok"
        penv = dict(os.environ, PATH=str(self.base / "bin") + os.pathsep + os.defpath)
        p = subprocess.run(
            [sys.executable, str(ROUTE_PY), *args],
            input="do the thing\nthe brief",
            env=penv,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return p

    def run_worker(self):
        return self.run_py("run", "worker", "--cwd", self.repo, "--unattended", "--timeout", "30")

    @real_proc("delegate: a worker, git or CLI process")
    def test_run_loads_the_pre_0_45_config_and_warns_once_per_retired_key(self):
        self.put_config()
        p = self.run_worker()
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout)["stop"] is None  # stdout is still exactly the answer
        warned = [ln for ln in p.stderr.splitlines() if "is retired" in ln]
        assert len(warned) == 3
        for key in ("codex_weekly_used_override", "codex_resume_after_stall", "credit"):
            assert len([w for w in warned if f"'{key}'" in w]) == 1
        assert all("config.json" in w and "safe to delete" in w for w in warned)
        assert (
            json.loads(Path(self.tmp.name, "config.json").read_text())["codex_weekly_used_override"] is None
        )  # the owner's file is never touched

    @real_proc("delegate: a worker, git or CLI process")
    def test_overrides_of_the_old_config_still_apply(self):
        self.put_config()
        cfg: Any = env.load_routing()
        assert (cfg["settings"]["max_parallel"], cfg["settings"]["strain"]["five_hour"]) == (3, 85)
        assert "codex_weekly_used_override" not in cfg["settings"]

    @real_proc("delegate: a worker, git or CLI process")
    def test_an_unknown_key_still_fails_and_names_file_key_and_fix(self):
        self.put_config({"codex_wekly_cap": 5})
        p = self.run_worker()
        assert p.returncode != 0
        assert p.stdout == ""
        for want in ("codex_wekly_cap", str(Path(self.tmp.name, "config.json")), "delete the key"):
            assert want in p.stderr

    @real_proc("delegate: a worker, git or CLI process")
    def test_doctor_reports_retired_keys_as_notes_not_errors(self):
        self.put_config()
        p = self.run_py("doctor", "--json")
        d = json.loads(p.stdout)
        notes = [n for n in d["notes"] if n["id"] == "retired_key"]
        assert sorted(n["key"] for n in notes) == ["codex_resume_after_stall", "codex_weekly_used_override", "credit"]
        assert all(n["file"].endswith("config.json") for n in notes)

    @real_proc("delegate: a worker, git or CLI process")
    def test_an_old_unversioned_state_file_is_reset_with_one_warning(self):
        self.put_config()
        Path(self.tmp.name, "state.json").write_text(
            json.dumps({"out": {"OPENAI_SUBSCRIPTION": {"until": 1, "why": "old"}}}), encoding="utf-8"
        )
        p = self.run_worker()
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout)["stop"] is None
        assert len([ln for ln in p.stderr.splitlines() if "state.json" in ln and "empty state" in ln]) == 1
        assert json.loads(Path(self.tmp.name, "state.json").read_text())["v"] == 1  # rewritten typed: the warning does not repeat

    @real_proc("delegate: a worker, git or CLI process")
    def test_split_retired(self):
        kept, gone = split_retired({"max_parallel": 2, RETIRED_SETTINGS[0]: None})
        assert (kept, gone) == ({"max_parallel": 2}, [RETIRED_SETTINGS[0]])
