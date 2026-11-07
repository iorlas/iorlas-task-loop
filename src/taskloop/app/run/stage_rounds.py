"""One round of a standalone write, checks, look or review step: its state from the checkpoint, the step, what it remembers."""
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.plancheck import RoundState

from taskloop.app.run.host import RunHost
from taskloop.app.write.prepare import PREPARED, Prepare
from taskloop.app.write.progress import progress_of, restore_progress
from taskloop.app.write.state import ACCEPT, REPLAN, StageState


def round_step(e: RunHost, step: Step, ck: Checkpoint | None) -> Step:
    s = round_state(e, step, ck)
    following, accepted = run_round_step(e, step, s)
    i = s.i
    if accepted:
        e.accepted.append(i)
        e.done.append(s.st["goal"])
        i += 1
        s.rounds, s.n, s.feedback = 0, 0, ""
        following = Step.VERIFY if s.last else Step.WRITE
    remember_round(e, s, following, i)
    return following


def round_state(e: RunHost, step: Step, ck: Checkpoint | None) -> StageState:
    plan = e.plan_data
    i = ck.stage if ck else 0
    if plan is None or i >= len(plan["stages"]):
        raise ValueError(f"{step} refused: no active plan stage; run --stage plan")
    counters: RoundState | None = None
    if ck and (ck.n or ck.rounds or ck.feedback):
        counters = {"rounds": ck.rounds, "n": ck.n, "feedback": ck.feedback}
    s = e.stage_loop.begin(plan, i, counters)
    if ck and ck.progress:
        restore_progress(s, ck.progress, e.writer_family or "")
    if step is not Step.WRITE and not s.w:
        raise ValueError(f"{step} refused: no recorded writer answer; run --stage write")
    s.run = e.last_run
    return s


def run_round_step(e: RunHost, step: Step, s: StageState) -> tuple[Step, bool]:
    if step is Step.WRITE:
        Prepare(e).run()
        s.n += 1
        e.stats["writes"] += 1
        flow = prepared_write(e, s)
        following = Step.REPLAN if flow == REPLAN else Step.WRITE if flow else Step.LOOK
    elif step is Step.LOOK:
        e.steps.begin(step, s.name)
        s.feedback = e.judge.look_step(s.st, s.w, s.name, s.last, checks=False, family=s.wfam)
        following = Step.WRITE if s.feedback else Step.CHECKS
    elif step is Step.CHECKS:
        flow = e.stage_loop.check(s)
        if flow == PREPARED:
            flow = prepared_write(e, s)
            return (Step.REPLAN if flow == REPLAN else Step.WRITE if flow else Step.LOOK), False
        following = Step.REPLAN if flow == REPLAN else Step.WRITE if flow else Step.REVIEW
    else:
        if s.run is None:
            raise ValueError("review refused: no recorded checks; run --stage checks")
        flow = e.stage_loop.review(s)
        following = Step.REPLAN if flow == REPLAN else Step.WRITE
        return following, flow == ACCEPT
    return following, False


def prepared_write(e: RunHost, s: StageState) -> str:
    """A prerequisite repair repeats the standalone write at the same attempt number."""
    while True:
        flow = e.stage_loop.write(s, look=False)
        if flow != PREPARED:
            return flow


def remember_round(e: RunHost, s: StageState, following: Step, i: int) -> None:
    progress = progress_of(s) if i == s.i else None
    e.checkpoints.save(step=following, stage=i, rounds=s.rounds, n=s.n, feedback=s.feedback, progress=progress)
    if s.run is not None:  # carry the check evidence forward across a separate look or review invocation
        e.stores.check_run(e.run_id, None).write(s.run)
