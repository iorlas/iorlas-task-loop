"""The checks of a round as Check records: the repo's (engine.checks) and the plan's (a stage's commands and cases)."""
from collections.abc import Sequence

from taskloop.contracts.argv import argv_of, text_of
from taskloop.contracts.checks import Check
from taskloop.contracts.config import CheckSpec, EngineConfig


def spelled(cmd: str) -> str:
    """The command in its one spelling (the argv joined), so two spellings of one argv are one check."""
    try:
        return text_of(argv_of(cmd))
    except ValueError:
        return cmd


def repo_check(k: CheckSpec, cfg: EngineConfig) -> Check:
    """A configured check, with the engine's limits where it names none."""
    idle = cfg.check_idle_min if k.idle_min is None else k.idle_min
    inputs = [k.inputs] if isinstance(k.inputs, str) else list(k.inputs)
    return Check(id=k.id, cmd=k.cmd, group=k.group, when=list(k.when), retry=k.retry,
                 timeout_min=float(k.timeout_min or cfg.check_timeout_min), idle_s=float(idle) * 60, cache=k.cache is not False,
                 inputs=inputs, inputs_only=k.inputs_only, exclude=list(k.exclude), env=dict(k.env), repo=True, writer=k.writer,
                 writer_max_s=k.writer_check_max_s, tail_log=k.tail_log)


def items_of(cfg: EngineConfig, stage_checks: Sequence[str]) -> list[Check]:
    """The repo's checks, then the plan's: a plan's check is its command, always run (it can read what git cannot see)."""
    idle = float(cfg.check_idle_min or 0) * 60
    plan = [Check(id=c, cmd=c, group="acceptance", timeout_min=float(cfg.check_timeout_min), idle_s=idle, cache=False)
            for c in map(spelled, stage_checks)]
    return [repo_check(k, cfg) for k in cfg.checks] + plan
