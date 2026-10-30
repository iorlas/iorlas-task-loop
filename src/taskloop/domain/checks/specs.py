"""The checks of a round as Check records: the repo's (engine.checks) and the plan's (a stage's commands and cases)."""
from collections.abc import Sequence

from taskloop.contracts.argv import argv_of, text_of
from taskloop.contracts.checks import Check
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.matchers import glob_re

DIFF_CHECK = CheckId("diff-check")  # the engine's own check: `git diff --check <base>`, always first in every round and the gate


def diff_check(base: str, tree: str) -> Check:
    """git's check of the diff from `base` to `tree`: leftover conflict markers and whitespace errors on changed lines (.gitattributes
    decides what counts), reading only the changed files. Cheap and static, so a red stops the expensive checks. Cached by tree and base."""
    return Check(id=DIFF_CHECK, cmd=f"git diff --check {base} {tree}", group="static", wall_min=2.0)


def spelled(cmd: str) -> str:
    """The command in its one spelling (the argv joined), so two spellings of one argv are one check."""
    try:
        return text_of(argv_of(cmd))
    except ValueError:
        return cmd


def repo_check(k: CheckSpec, cfg: EngineConfig, gate: bool = False) -> Check:
    """A configured check, with the engine's limits where it names none (in the gate: engine.gate_timeout_min)."""
    inputs = [k.inputs] if isinstance(k.inputs, str) else list(k.inputs)
    return Check(id=k.id, cmd=k.cmd, group=k.group, when=list(k.when), retry=k.retry,
                 wall_min=float(k.wall_min or (cfg.gate_timeout_min if gate else cfg.check_wall_min)), cache=k.cache is not False,
                 inputs=inputs, inputs_only=k.inputs_only, exclude=list(k.exclude), env=dict(k.env), repo=True, writer=k.writer,
                 writer_max_s=k.writer_check_max_s, tail_log=k.tail_log,
                 fix=text_of(k.fix) if k.fix else "", container=k.where == "container")


def items_of(cfg: EngineConfig, stage_checks: Sequence[str]) -> list[Check]:
    """The repo's checks, then the plan's: a plan's check is its command, always run (it can read what git cannot see)."""
    plan = [Check(id=CheckId(c), cmd=c, group="acceptance", wall_min=float(cfg.check_wall_min), cache=False)
            for c in map(spelled, stage_checks)]
    return [repo_check(k, cfg) for k in cfg.stage_checks] + plan


def gate_items(cfg: EngineConfig) -> list[Check]:
    """The gate's steps: the checks that run at land (run gate or both)."""
    return [repo_check(k, cfg, gate=True) for k in cfg.gate_checks]


def due(c: Check, changed: Sequence[str]) -> bool:
    """A check with `when` is due only when a changed path matches one of its globs (the one glob dialect: ** crosses
    folders, * stays in one)."""
    return not c.when or any(glob_re(g).match(p) for p in changed for g in c.when)
