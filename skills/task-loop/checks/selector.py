"""The selector hook (tl-7y6.7.18) and its shadow mode (tl-7y6.7.21): `engine.selector` is a command that names the repo checks
a change needs. Absent, the engine runs every check, as before.

Contract: the command runs in the worktree with TL_SELECT_STAGE (write | fix | land | gate), TL_SELECT_BASE (the base commit) and
TL_SELECT_SINCE (a tree: the last green round's, for a fix round; empty otherwise) in its environment, and prints one JSON object
{"checks": [ids], "hatch": str|null, "reason": str}. Two diffs: write, land and gate use diff-vs-base; a fix round uses
diff-vs-since plus whatever was red. A hatch always escalates to the full set; so does a nonzero exit or output that is not that
JSON (with a warning in the record). Only repo checks are selectable: a stage's own checks always run.
Pure functions and two small typed records; no engine state."""

import json
import os
import subprocess
from dataclasses import asdict, dataclass

STAGES = ("write", "fix", "land", "gate")
TIMEOUT_S = 120


@dataclass(frozen=True)
class Selection:
    """What the selector said. warning: why it could not be used (the full set runs)."""
    checks: tuple = ()
    hatch: str = ""
    reason: str = ""
    warning: str = ""

    @property
    def full(self):
        return bool(self.hatch or self.warning)


@dataclass(frozen=True)
class Picked:
    """The engine's use of a selection for one round: the repo checks that run and those skipped (stored `skipped: selector`)."""
    stage: str
    since: str
    selected: tuple
    skipped: tuple
    hatch_reason: str = ""
    warning: str = ""

    def record(self):
        return asdict(self)


@dataclass(frozen=True)
class Shadow:
    """Shadow mode, one round of one bead: the selector's set against the full set that ran, and the failures it would have hidden."""
    bead: str
    stage: str
    full: tuple
    selected: tuple
    would_skip: tuple
    missed: tuple  # would_skip ids that failed in the full run
    hatch_reason: str = ""
    warning: str = ""
    gate_exit: object = None  # the gate's exit when stage == gate (its tests are not listed per check)

    def record(self):
        return asdict(self)


def ask(cmd, stage, base, since, cwd, run=subprocess.run):
    """Run the selector. Any failure comes back as a Selection with a warning, never an exception."""
    env = dict(os.environ, TL_SELECT_STAGE=stage, TL_SELECT_BASE=base or "", TL_SELECT_SINCE=since or "")
    try:
        p = run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return Selection(warning="selector failed to run: %s" % str(e)[:200])
    if p.returncode != 0:
        return Selection(warning="selector exit %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-200:]))
    try:
        d = json.loads(p.stdout)
        ids, hatch, reason = d["checks"], d.get("hatch"), d.get("reason", "")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or not isinstance(reason, str) or not (
                hatch is None or isinstance(hatch, str)):
            raise TypeError("wrong field types")
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        return Selection(warning="selector output is not {checks, hatch, reason} JSON: %s" % str(e)[:120])
    return Selection(tuple(ids), hatch or "", reason)


def pick(ids, sel, stage, since="", forced=()):
    """Split the repo check ids into (selected, skipped). The full set when sel.full; `forced` (what was red) always stays in."""
    ids = list(ids)
    if sel.full:
        return Picked(stage, since, tuple(ids), (), sel.hatch, sel.warning)
    keep = set(sel.checks) | set(forced)
    return Picked(stage, since, tuple(i for i in ids if i in keep), tuple(i for i in ids if i not in keep), "", "")


def shadow(bead, stage, picked, results, gate_exit=None):
    """What the selector would have skipped in a round that ran everything: `results` is the round's [{id, status, group}]."""
    ran = {r["id"]: r for r in results}
    skip = picked.skipped
    return Shadow(bead, stage, tuple(i for i in picked.selected + picked.skipped), picked.selected, skip,
                  tuple(i for i in skip if (ran.get(i) or {}).get("status") == "failed"), picked.hatch_reason, picked.warning, gate_exit)
