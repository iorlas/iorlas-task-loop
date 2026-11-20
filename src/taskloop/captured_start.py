"""Start a captured attempt by repairing its answer before considering a Git repeat."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from taskloop.attempt_types import AttemptKey, EntryIdentity
    from taskloop.operations import Failed, Started, StartPorts, StartRequest


class AnswerRepairing(Protocol):
    def route(self, backlog: str, task_id: str, previous: AttemptKey, minutes: int) -> Started | Failed | None: ...


def start_captured(ports: StartPorts, request: StartRequest, key: AttemptKey, entry: EntryIdentity | None) -> Started | Failed:
    repaired = (None if ports.answer_repair is None else
                ports.answer_repair.route(request.backlog, request.task_id, key, request.minutes))
    return repaired if repaired is not None else ports.repeat.repeat(request.backlog, request.task_id, key, entry, request.minutes)
