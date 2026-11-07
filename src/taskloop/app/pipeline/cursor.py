"""Pure step cursor selection from run manifests and checkpoints."""
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.kinds import Kind
from tlkernel.locator import RunBundle
from tlkernel.run import RunState


def parse_step(name: str) -> Step:
    try:
        return Step(name)
    except ValueError:
        raise ValueError(f"unknown stage {name!r}; choose from: {', '.join(Step)}") from None


def stage_kind(step: Step) -> Kind:
    """What one stage's run ends as: only a land is landed and only a close (or the reflect after it) is done."""
    if step is Step.LAND:
        return Kind.LANDED
    return Kind.DONE if step in (Step.CLOSE, Step.REFLECT) else Kind.STAGE


def manifest_next(last: RunBundle | None, ck: Checkpoint | None) -> Step | None:
    if last is None:
        return None
    if ck is None or last.run == ck.run or last.started >= ck.t:
        return last.manifest.next_step
    return None


def select_step(last: RunBundle | None, ck: Checkpoint | None, fresh: bool, requested: str | None) -> Step:
    """Select the cursor without opening or changing a run."""
    if last and last.manifest.state.live:
        raise ValueError(f"previous run {last.run} is still {last.manifest.state}")
    if requested:
        return parse_step(requested)
    if fresh:
        return Step.RESET
    recorded = manifest_next(last, ck)
    if recorded is not None:
        return recorded
    if ck is not None:
        return checkpoint_next(ck)
    if last and last.manifest.state is RunState.DONE:
        raise ValueError("the last run is complete and has no next stage; name --stage or use --fresh")
    return Step.RESET


def checkpoint_next(ck: Checkpoint) -> Step:
    if ck.ended is not None:
        return Step.CLOSE
    if ck.step in ("gate-red", "land-verify-red"):
        return Step.REPLAN
    return parse_step(ck.step or "plan")
