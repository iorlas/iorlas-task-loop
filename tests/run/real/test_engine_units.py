"""Engine tests, part 2: the small classes after EngineTest (failure brief, outcome, delegate launcher, stored briefs, confirms,
validate). Split from test_engine."""

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
import support.paths  # noqa: E402, F401

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support import engine_case as T  # noqa: E402
from support.engine_case import (  # noqa: E402
    PLAN,
    WRITE,
    full,
    real_git,
    stop,
)

from taskloop.adapters import delegate as lroute  # noqa: E402
from taskloop.app.run import (  # noqa: E402
    entry,
)
from taskloop.contracts.env import snapshot  # noqa: E402
from taskloop.domain.checks import (  # noqa: E402
    lint,  # noqa: F401
)


class Outcome(T.EngineTest):
    """What run-task tells the loop (tl loop): landed, parked, paused, failed or taken, as one JSON record."""


    def main(self, outcome_file, **kw):
        a = mock.Mock(id="t-1", worktree=str(Path(self.tmp.name, "slot")), slot=None, dry_run=False, fresh=False,
                      quiet=True, outcome_file=str(outcome_file))
        Path(a.worktree).mkdir(exist_ok=True)
        out = io.StringIO()
        with contextlib.chdir(self.wt), redirect_stdout(out), mock.patch.object(signal, "signal"):  # pyrefly: ignore[missing-attribute]
            rc = entry.main(a, self.store, env=snapshot())  # pyrefly: ignore[missing-attribute]
        last = json.loads(out.getvalue().strip().splitlines()[-1])
        return rc, json.loads(Path(outcome_file).read_text()), last


class DelegateLauncher(T.EngineTest):


    # lifesim-d5f.58 2026-10-21: a resumed Codex writer answered lane_out for an hour and the bead paused; delegate never
    # switches lanes on a resume, but a fresh call gets the role's next rung (Sonnet on the claude lane) at once
    OUT_LONG = stop("rate_limited", at=time.time() + 3600, say="cannot continue t now")
    # delegate says the writer fell back off its first lane (to xai, so the reviewer, claude, is another family)
    FRESH = full(WRITE, "w2", fallback=True, first_lane="OPENAI_SUBSCRIPTION", family="xai")


    # tl-bxk.10.5 2026-10-21: after a real outage the Sonnet thread stayed the writer for every later round of
    # lifesim-fld.27.7, d5f.33, 1eg2 and d5f.54 while Codex was usable again
    BACK = full(WRITE, "w3", family="openai", lane="OPENAI_SUBSCRIPTION", model="gpt")
    OUT_L: ClassVar[Any] = dict(OUT_LONG, lane="OPENAI_SUBSCRIPTION")

    def transitions(self):
        return [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"transition"' in ln]

    def lanes(self, **out):
        """`route.py status --json` lanes: name -> {out}."""
        return mock.patch.object(lroute, "lane_status", return_value={k: {"out": v} for k, v in out.items()})


    # contract 3: an answer that picked a lane says whether it is a fallback (and from which first lane, when it can)
    SONNET_FB: ClassVar[Any] = dict(FRESH, rung=1, fallback=True, fallback_reason="ceiling", first_lane="OPENAI_SUBSCRIPTION")
    CODEX_FIRST: ClassVar[Any] = dict(BACK, rung=0, fallback=False, fallback_reason=None)
    no_checks: ClassVar[Any] = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[])])  # FRESH writes no f.txt


    # lifesim-5ar.6 2026-10-21: the resumed writer's lane_out came with no retry_after, so next was owner, and the bead
    # blocked "needs a human" after 114 min of work
    OUT_OWNER = stop("rate_limited", say="cannot say when OPENAI_SUBSCRIPTION frees")


    # lifesim 2026-10-20: woken from sleep, Codex ended its turn after 12 s with a vendor error and no tokens; delegate
    # 0.26 answered failed and the engine closed two beads as failed
    QUICK = stop("vendor_blip", "w1", say="codex failed before any work: workspace routing discovery failed")


    # tl-bxk.10.22: the dashboard says which lane a run waits for and until when


    LOGIN_CLAUDE = "run `claude auth login`"


    # contract 3: logged_out is lane / needs_owner: the lane waits for its owner, the step never retries it and never asks


class NoBackgroundGit(T.EngineTest):
    @real_git("asserts the git config of the real template and clone repos")
    def test_template_and_clone_repos_never_auto_gc_or_maintain(self):
        for repo in (T._template() / "o.git", T._template() / "wt", self.tmp_repo("o.git"), self.tmp_repo("wt")):
            for key, want in (("maintenance.auto", "false"), ("gc.auto", "0")):
                got = subprocess.run(
                    ["git", "-C", str(repo), "config", "--local", "--get", key], capture_output=True, text=True, check=False
                )
                self.assertEqual(got.stdout.strip(), want, f"{repo} {key}")
        self.assertEqual(os.environ["GIT_CONFIG_KEY_0"], "maintenance.auto")  # the env covers every other git call

    def tmp_repo(self, name):
        return Path(self.tmp.name) / name


if __name__ == "__main__":
    unittest.main()
