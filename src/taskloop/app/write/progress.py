"""A stage's progress inside a round, as the checkpoint keeps it (StageProgress): written by the standalone step runner after each step
and by StageLoop when a round's checks are green, read back where a stage goes on."""
from taskloop.app.write.state import StageState
from taskloop.contracts import wire
from taskloop.contracts.answers import WriteAnswerLook
from taskloop.contracts.checkpoint import StageProgress


def progress_of(s: StageState) -> StageProgress:
    known = wire.keys(WriteAnswerLook)  # (the answer may carry more: the engine adds to it)
    body = {k: v for k, v in dict(s.w, logic_only=s.w.get("logic_only", "")).items() if k in known}
    answer = wire.load(WriteAnswerLook, body) if s.w else None
    return StageProgress(write=answer, red=s.red, red_now=sorted(s.red_now), failed=s.failed_cmds, acceptance_only=s.acc_only,
                         acceptance_first=s.acc_first, shots_fixed=s.shots_fixed, show_fixed=s.show_fixed)


def restore_progress(s: StageState, p: StageProgress, family: str) -> None:
    """`family`: the writer's family (RunState.writer_family)."""
    s.red, s.red_now, s.failed_cmds = p.red, set(p.red_now), p.failed
    s.acc_only, s.acc_first, s.shots_fixed = p.acceptance_only, p.acceptance_first, p.shots_fixed
    s.show_fixed = p.show_fixed
    s.w = wire.dump(p.write) if p.write else {}
    s.wfam = family
    s.wrote_unchecked = s.w.get("unchecked") or []
