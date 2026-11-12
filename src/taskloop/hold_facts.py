"""What a hold's comment states, read when the hold writes it (tl-8bh9.14.9 sections 6 and 12): the abandon's outcome
(`outcome`: the claim returned, kept by a refusal only the person clears, or a transient refusal the next round retries),
and the facts of the hold and its cause (`facts`). Reads only: the stored rows, the slot path, a registered process and
the agent's explanation from its stored valid answer (decoded by the step kind's own decoder, never a second parser).
Agent text goes to the person only, through `hold_text`."""

from dataclasses import dataclass
from typing import get_args

from any_agent import DecodedAnswer, decode_answer

from taskloop.attempt_reads import AttemptRow
from taskloop.attempt_status import AttemptView
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import StoredExecution
from taskloop.check_status import latest
from taskloop.check_store import CheckStore
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.hold_store import HoldRow
from taskloop.hold_text import FailedCheck, HoldFacts, Kept, KeptWord, LabelsWord, Leftovers, Returned
from taskloop.operations import Failed, ReleasedTask
from taskloop.setup_store import SetupStore
from taskloop.steps import is_agent, kind


@dataclass(frozen=True)
class Pending:
    """The abandon did not finish and nothing the person must do is known yet (`slot_busy`, `unavailable:*`,
    `worker_unknown`, ...): no comment; the next round tries again. `word` is the refusal's."""

    word: str


def refusal(failed: Failed) -> str:
    """The abandon refusal's word as a round's line shows it: `held:<slot word>` for a slot left as it is, else the
    refusal's own (`unsettled:worker_alive`, `unavailable:tracker`, `refused:landing`)."""
    return f"held:{failed.reason}" if failed.kind == "refused" and failed.reason.startswith("slot_") else failed.word


def outcome(reader: AttemptStore, agent: AttemptRow, released: ReleasedTask | Failed) -> Returned | Kept | Pending:
    """`Returned` once the abandon recorded the claim as no longer the factory's; `Kept` for section 12's refusals only the
    person clears, naming the slot or the process; `Pending` otherwise (an `unclaiming` claim too: the unclaim is retried)."""
    if isinstance(released, ReleasedTask):
        claim = released.result.claim
        return Returned(claim) if claim in ("unclaimed", "not_held") else Pending(f"release:{claim}")
    word = next((each for each in get_args(KeptWord.__value__) if each == released.reason), None)
    if word is None:
        return Pending(refusal(released))
    checks = latest(CheckStore(reader.connect, reader.begin), agent.key.attempt_id) if released.checks else None
    held = agent.key if checks is None else checks.key
    slot = reader.slot_path(held.attempt_id) or ""
    if word == "worker_alive" and agent.worker is not None:
        return Kept(word, slot, *agent.worker)
    if word == "setup_running":
        setup = SetupStore(reader.connect, reader.begin).latest(held)
        found = None if setup is None else setup.unsettled
        return Kept(word, slot) if found is None else Kept(word, slot, found.pid, found.pgid)
    if word == "check_running" and checks is not None:
        found = next((row.process for row in CheckStore(reader.connect, reader.begin).results(checks.key)
                      if row.unsettled and row.process is not None), None)
        return Kept(word, slot) if found is None else Kept(word, slot, found.pid, found.pgid)
    return Kept(word, slot)


def explanation(files: EvidenceFiles, execution: StoredExecution | None, step: str, task_id: str) -> str | None:
    """The agent's explanation from its stored valid answer, by the step kind's own decoder; None without one (no valid
    answer, a checks attempt, or an answer file that no longer reads as stored)."""
    if execution is None or execution.answer.kind != "valid" or not is_agent(step):
        return None
    found = kind(step)
    rules = found.rules(task_id)
    try:
        answer = decode_answer(files.read(execution.evidence.answer), lambda value: found.decode(value, rules))
    except EvidenceError:
        return None
    return answer.value.explanation if isinstance(answer, DecodedAnswer) else None


def facts(files: EvidenceFiles, view: AttemptView, row: HoldRow, labels: LabelsWord, agent: AttemptRow) -> HoldFacts:
    """The comment's facts: the cause as the view shows it (a checks view: the checks attempt, its failed checks and their
    logs), A's X and publication, the leftovers of a `repeats_exhausted` hold and the cause's evidence directory."""
    checks = view.checks
    key = agent.key if checks is None else checks.row.key
    failed = () if checks is None else tuple(
        FailedCheck(each.name, each.conclusion or "unfinished",
                    "" if each.conclusion == "undefined" else str(files.check_path(key, each.block, each.name)))
        for each in checks.results if each.conclusion != "passed")
    left = Leftovers(view.leftovers[0], view.leftovers[1:]) if view.leftovers and row.reason.startswith("repeats_exhausted") else None
    told = None if checks is not None else explanation(files, view.result.execution, view.step, view.task_id)
    published = None if view.published is None else view.published.commit
    return HoldFacts(view.task_id, row.label, labels, row.reason, view.step, view.number, view.attempt_id, row.held_at, published,
                     agent.end_commit, told, failed, left, str(files.root / files.directory(key)))
