"""tl report: the owner's comments against the engine's."""
import io
import json
import os
import re
import shutil
import stat
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support import homes  # noqa: E402

from tltestkit.runs import manifest  # noqa: E402

# isort: split
import tl  # noqa: E402

from taskloop.app.report import planner  # noqa: E402
from tlkernel import lifecyclematchers as matchers  # noqa: E402
from tltestkit.checked import run_checked  # noqa: E402

T0 = datetime(2026, 10, 21, 6, 0).timestamp()  # the window's start in the fixtures: local 06:00
MIN = 60.0


def git(repo, *args, t=None):
    env = dict(os.environ)
    if t is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(t)} +0000"
    r = run_checked(["git", "-C", str(repo), *args], None, text=True, env=env)
    return r.stdout.strip()


def commit(repo, name, text, msg, t):
    (Path(repo) / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg, t=t)
    return git(repo, "rev-parse", "HEAD")


class Base(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, "a.txt", "a\n", "init", T0 - 600 * MIN)

    def teardown_method(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)


# ---- the window -------------------------------------------------------------------------------------------------------

class ParseTime(Case):
    NOW = datetime(2026, 10, 21, 20, 30).timestamp()

    def test_hh_mm_is_today(self):
        assert matchers.parse_time("06:00", self.NOW) == datetime(2026, 10, 21, 6, 0).timestamp()

    def test_durations_count_back_from_now(self):
        assert matchers.parse_time("12h", self.NOW) == self.NOW - 12 * 3600
        assert matchers.parse_time("90m", self.NOW) == self.NOW - 90 * 60
        assert matchers.parse_time("2d", self.NOW) == self.NOW - 2 * 86400

    def test_iso_local_and_with_offset(self):
        assert matchers.parse_time("2026-10-20T22:15", self.NOW) == datetime(2026, 10, 20, 22, 15).timestamp()
        assert matchers.parse_time("2026-10-20 22:15", self.NOW) == datetime(2026, 10, 20, 22, 15).timestamp()
        assert matchers.parse_time("2026-10-20", self.NOW) == datetime(2026, 10, 20).timestamp()
        assert matchers.parse_time("2026-10-21T03:00:00Z", self.NOW) == 1792551600.0

    def test_since_hh_mm_rolls_back_until_rolls_forward(self):
        morning = datetime(2026, 10, 21, 7, 0).timestamp()
        assert matchers.parse_time("22:00", morning) == datetime(2026, 10, 20, 22, 0).timestamp()
        assert matchers.parse_time("22:00", morning, forward=True) == datetime(2026, 10, 21, 22, 0).timestamp()
        assert matchers.parse_time("06:00", morning, forward=True) == datetime(2026, 10, 22, 6, 0).timestamp()

    def test_nonsense_is_refused(self):
        with pytest.raises(ValueError):
            matchers.parse_time("yesterday-ish", self.NOW)


# ---- 10.2: lost work --------------------------------------------------------------------------------------------------


# ---- 10.1: the scorecard ----------------------------------------------------------------------------------------------

def trace(bead, outcome, start_min, end_min, why="", sha="", rounds=0, replans=0, sessions=(), worktree=None, run=None,
          stderr=None, kind=""):
    started, ended = T0 + start_min * MIN, T0 + end_min * MIN
    stem = run or "{}-{}".format(bead, time.strftime("%Y%m%d-%H%M%S", time.localtime(started)))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/r.git", "worktree": worktree,
            "started": started, "ended": ended, "outcome": outcome, "why": why, "sha": sha,
            "stats": {"rounds": rounds, "replans": replans}, "log": str(homes.config_dir() / "runs" / stem / "engine.jsonl"),
            "sessions": list(sessions), "stderr": stderr, "kind": kind}


def session(role, family, tin, cached, out):
    return {"role": role, "family": family, "tokens": {"in": tin, "cached": cached, "out": out}}


class PlannerReport(Case):
    """tl-bxk.10.13: planner calls per bead and their input tokens, from the engine logs."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "cfg"),
                                                "APPDATA": str(home / "cfg")})
        self.env.start()
        self.eng = homes.config_dir() / "runs"
        calls = [("planner", "x-1", 1000, 9000), ("planner", "x-1", 500, 4500), ("planner", "x-1", 200, 800),
                 ("planner", "x-1", 100, 100), ("worker", "x-1", 9999, 9999), ("planner", "x-2", 300, 700),
                 ("planner", "y-9", 1, 1)]
        texts = ["plan: plan", "plan: re-plan", "plan: rewrite checks", "plan: amend"]
        for bead in ("x-1", "x-2", "y-9"):
            records: list[dict[str, object]] = []
            for k, (role, task, tin, cached) in enumerate(calls):
                if task != bead:
                    continue
                if role == "planner" and bead != "y-9":
                    records.append({"t": T0 + k, "kind": "step_start", "id": f"n{k}", "step": "plan",
                                    "text": texts[k] if bead == "x-1" else "plan: plan"})
                records.extend([
                    {"t": T0 - 10, "kind": "call_start", "id": f"c{k}", "role": role, "step": "plan", "node": f"n{k}"},
                    {"t": T0 + k, "kind": "call_end", "id": f"c{k}", "tokens": {"in": tin, "cached": cached, "out": 5}},
                ])
            records.append({"t": T0, "kind": "call_end", "id": "unmatched", "tokens": {"in": 9999}})
            manifest(homes.config_dir(), f"{bead}-20261021-060000", bead, T0 - 20).log.write_text(
                "".join(json.dumps(rec) + "\n" for rec in records))

    def teardown_method(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_calls_are_split_into_first_again_amend_and_send_back_and_input_is_in_plus_cached(self):
        p = planner.planner_stats(homes.cfg(), T0 - 1, T0 + 100)
        by = {x["bead"]: x for x in p["per_bead"]}
        assert (
            {k: by["x-1"][k] for k in ("calls", "first", "again", "amend", "back", "other", "input")}
            == {"calls": 4, "first": 1, "again": 1, "amend": 1, "back": 1, "other": 0, "input": 16100}
        )
        assert (by["x-2"]["calls"], by["x-2"]["first"], by["x-2"]["input"]) == (1, 1, 1000)
        assert (p["calls"], p["beads"], p["input"]) == (6, 3, 17101)  # the worker call is no planner call
        only = planner.planner_stats(homes.cfg(), T0 - 1, T0 + 100, {"x"})
        assert (only["calls"], only["beads"]) == (5, 2)
        assert planner.planner_stats(homes.cfg(), T0 + 50, T0 + 100)["calls"] == 0  # outside the window

    def test_window_uses_call_end_time_inclusively_even_when_the_start_is_earlier(self):
        p = planner.planner_stats(homes.cfg(), T0 + 1, T0 + 2)
        assert (p["calls"], p["beads"], p["input"]) == (2, 1, 6000)

    def test_call_ids_match_only_within_the_same_log(self):
        start = manifest(homes.config_dir(), "split-start", "x-1", T0)
        end = manifest(homes.config_dir(), "split-end", "x-1", T0)
        start.log.write_text(json.dumps({"t": T0, "kind": "call_start", "id": "split", "role": "planner"}) + "\n")
        end.log.write_text(json.dumps({"t": T0, "kind": "call_end", "id": "split", "tokens": {"in": 9999}}) + "\n")
        p = planner.planner_stats(homes.cfg(), T0 - 1, T0 + 100)
        assert (p["calls"], p["input"]) == (6, 17101)

    def test_input_is_in_when_in_already_holds_the_cache_else_in_plus_cached(self):
        assert planner.input_tokens({"in": 10000, "cached": 9000}) == 10000   # delegate 0.22+ and Codex
        assert planner.input_tokens({"in": 1000, "cached": 9000}) == 10000    # before 0.22: uncached-only in
        assert planner.input_tokens({"in": 5, "cached": 0}) == 5
        assert planner.input_tokens({}) == 0

    def test_the_cli_prints_the_planner_table_read_only(self):
        before = sorted(p.name for p in self.eng.iterdir())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = tl.main(["report", "--planner", "--prefix", "x", "--since", "2026-10-21", "--until", "2026-10-22"])
        text = out.getvalue()
        assert rc == 0
        assert "planner: 5 calls on 2 beads" in text
        assert re.search(r"x-1\s+4\s+1\s+1\s+1\s+1\s+0\s+0\.02", text)
        assert before == sorted(p.name for p in self.eng.iterdir())
