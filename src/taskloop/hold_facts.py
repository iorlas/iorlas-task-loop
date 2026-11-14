"""What a hold's comment states, read when the hold writes it (tl-8bh9.14.9 sections 6 and 12): the abandon's outcome
(`outcome`: the claim returned, kept by a refusal only the person clears, or a transient refusal the next round retries),
and the facts of the hold and its cause (`facts`). Reads only: the stored rows, the slot path, a registered process and
the agent's explanation from its stored valid answer (decoded by the step kind's own decoder, never a second parser).
Agent text goes to the person only, through `hold_text`."""

from dataclasses import dataclass
from typing import get_args

from any_agent import DecodedAnswer, decode_answer

from taskloop.attempt_reads import AttemptRow, StoreRefused
from taskloop.attempt_result import collect
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import StoredExecution
from taskloop.check_status import latest
from taskloop.check_store import CheckStore
from taskloop.command_conclusion import CommandConclusion, encode
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.hold_store import HoldRow
from taskloop.hold_text import FailedCheck, HoldFacts, Kept, KeptWord, LabelsWord, Leftovers, Returned
from taskloop.merge.store import MergeStore
from taskloop.operations import Failed, ReleasedTask
from taskloop.setup_store import SetupStore
from taskloop.steps import CHECK, is_agent, kind


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


def facts(files: EvidenceFiles, reader: AttemptStore, row: HoldRow, labels: LabelsWord, agent: AttemptRow,
          leftovers: tuple[str, ...]) -> HoldFacts:
    """The comment's facts, from the stored hold, never from whichever view the caller has now (after the abandon a
    checks cause's task shows its implement attempt): a checks cause (`cause_id` is not A) is that checks attempt, its
    latest block's failed checks with their logs and its evidence directory, with no agent explanation; an agent cause
    is A with its stored answer's explanation and (`repeats_exhausted`) the `leftovers` the caller read. A's X and
    publication either way. StoreRefused `changed` when the checks cause is no longer stored."""
    published = None if agent.published is None else agent.published.commit
    head = (agent.task_id, row.label, labels, row.reason)
    if row.cause_id != row.attempt_id:
        store = CheckStore(reader.connect, reader.begin)
        checks = next((each for each in store.of_attempt(row.attempt_id) if each.key.attempt_id == row.cause_id), None)
        if checks is None:
            raise StoreRefused("changed")
        failed = tuple(
            FailedCheck(each.name, encode(each.conclusion) or "unfinished",
                        "" if each.conclusion == CommandConclusion.UNDEFINED else str(files.check_path(checks.key, each.block, each.name)))
            for each in store.results(checks.key) if each.conclusion != CommandConclusion.PASSED)
        return HoldFacts(*head, CHECK, checks.number, row.cause_id, row.held_at, published, agent.end_commit, None, failed, None,
                         str(files.root / files.directory(checks.key)), files.last_entry(checks.key), checks.deadline)
    left = Leftovers(leftovers[0], leftovers[1:]) if leftovers and row.reason.startswith("repeats_exhausted") else None
    told = explanation(files, collect(reader, agent.key).execution, agent.step, agent.task_id)
    merge = MergeStore(reader.connect, reader.begin).get(agent.key.attempt_id) if row.reason.startswith("merge:") else None
    told = told if merge is None else merge.explanation
    return HoldFacts(*head, agent.step, agent.number, agent.key.attempt_id, row.held_at, published, agent.end_commit, told, (),
                     left, str(files.root / files.directory(agent.key)), files.last_entry(agent.key), agent.deadline)
