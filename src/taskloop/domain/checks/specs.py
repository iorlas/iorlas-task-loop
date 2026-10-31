"""The checks of a round as Check records: the repo's (engine.checks) and the plan's (a stage's commands and cases)."""
from collections.abc import Sequence
from typing import Final, assert_never

from taskloop.contracts.argv import text_of
from taskloop.contracts.checks import Check, Phase, Tag
from taskloop.contracts.config import CheckSpec, EngineConfig
from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import Adhoc, PlanCheck
from taskloop.domain.checks.matchers import glob_re, is_build, is_unity
from taskloop.domain.checks.planref import adhocs

DIFF_CHECK: Final = CheckId("diff-check")  # the engine's own check: `git diff --check <base>`, always first in every round and the gate


def diff_check(base: str, tree: str) -> Check:
    """git's check of the diff from `base` to `tree`: leftover conflict markers and whitespace errors on changed lines (.gitattributes
    decides what counts), reading only the changed files. Cheap and static, so a red stops the expensive checks. Cached by tree and base."""
    return Check(id=DIFF_CHECK, cmd=f"git diff --check {base} {tree}", group="static", wall_min=2.0, tags=["diff"])


def tags_of(check_id: str, cmd: str) -> list[Tag]:
    """The tags of a repo check: read from its id and command once, here, so nothing downstream matches text again."""
    text = f"{check_id} {cmd}"
    tags: list[Tag] = []
    if is_unity(text):
        tags.append("unity")
    if is_build(text):
        tags.append("build")
    return tags


def wall_limit(k: CheckSpec | None, cfg: EngineConfig, phase: Phase) -> float:
    """The one place a check's wall limit (minutes) is decided: its own, else the phase's (the gate has engine.gate_timeout_min)."""
    own = k.wall_min if k else None
    match phase:
        case Phase.STAGE:
            return float(own or cfg.check_wall_min)
        case Phase.GATE:
            return float(own or cfg.gate_timeout_min)
        case never:
            assert_never(never)


def repo_check(k: CheckSpec, cfg: EngineConfig, phase: Phase = Phase.STAGE) -> Check:
    """A configured check, with the engine's limits where it names none (in the gate: engine.gate_timeout_min)."""
    inputs = [k.inputs] if isinstance(k.inputs, str) else list(k.inputs)
    return Check(id=k.id, cmd=k.cmd, group=k.group, when=list(k.when), retry=k.retry,
                 wall_min=wall_limit(k, cfg, phase), cache=k.cache is not False,
                 inputs=inputs, inputs_only=k.inputs_only, exclude=list(k.exclude), env=dict(k.env), repo=True, writer=k.writer,
                 writer_max_s=k.writer_check_max_s, tail_log=k.tail_log, keep=list(k.keep), needs=list(k.needs), lane=k.lane,
                 fix=text_of(k.fix) if k.fix else "", container=k.where == "container", reads=list(k.reads), tags=tags_of(k.id, k.cmd))


def adhoc_check(a: Adhoc, cfg: EngineConfig) -> Check:
    """A command of the plan's own as a check: always run (it can read what git cannot see), after the checks it reads. An adhoc
    has no registry id; its one-line text is its id."""
    return Check(id=CheckId(a.text), cmd=a.text, group="acceptance", wall_min=wall_limit(None, cfg, Phase.STAGE), cache=False,
                 reads=list(a.reads))


def items_of(cfg: EngineConfig, stage_checks: Sequence[PlanCheck]) -> list[Check]:
    """The repo's checks, then the plan's own: a ref names a registered check the round runs anyway."""
    return [repo_check(k, cfg) for k in cfg.stage_checks] + [adhoc_check(a, cfg) for a in adhocs(stage_checks)]


def gate_items(cfg: EngineConfig) -> list[Check]:
    """The gate's steps: the checks that run at land (run gate or both)."""
    return [repo_check(k, cfg, Phase.GATE) for k in cfg.gate_checks]


def due(c: Check, changed: Sequence[str]) -> bool:
    """A check with `when` is due only when a changed path matches one of its globs (the one glob dialect: ** crosses
    folders, * stays in one)."""
    return not c.when or any(glob_re(g).match(p) for p in changed for g in c.when)
