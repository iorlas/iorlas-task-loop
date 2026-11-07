"""review_skip: a stage whose every changed path is mechanical (domain/work/skip.py) is accepted without a review call. The diff is
read here; the rule is the domain's."""
from tlkernel.config import EngineConfig
from tlkernel.gitport import Git

from taskloop.domain.work.skip import SkipKind, decide


def why(git: Git, wt: str, start: str, now: str, cfg: EngineConfig, *, maps_acceptance: bool) -> tuple[SkipKind, ...]:
    """The reasons the stage from tree `start` to tree `now` needs no review, () when it does (or when git cannot say)."""
    if not now or not start:
        return ()
    entries = git.diff_entries(wt, start, now, required=True)
    significant = {x.path for x in git.diff_entries(wt, start, now, ignore_space=True, required=True)}
    return decide(entries, significant, cfg.skip_review, has_formatter=any(k.fix for k in cfg.stage_checks),
                  maps_acceptance=maps_acceptance)
