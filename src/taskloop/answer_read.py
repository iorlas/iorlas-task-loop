"""Decode stored agent answers through the owning step, without presentation policy."""

from any_agent import DecodedAnswer, decode_answer

from taskloop.attempt_types import Answer, StoredExecution
from taskloop.evidence_files import EvidenceFiles
from taskloop.steps import is_agent, kind


def read(files: EvidenceFiles, execution: StoredExecution | None, step: str, task_id: str) -> Answer | None:
    """None for an absent or invalid answer; unreadable digest-bearing evidence raises EvidenceError."""
    if execution is None or execution.answer.kind != "valid" or not is_agent(step):
        return None
    found = kind(step)
    answer = decode_answer(files.read(execution.evidence.answer), lambda value: found.decode(value, found.rules(task_id)))
    return answer.value if isinstance(answer, DecodedAnswer) else None
