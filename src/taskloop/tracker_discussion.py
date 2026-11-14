"""Tracker interchange for directly linked discussion, scoped to the configured backlog."""

from typing import Protocol

from beads_client import TaskReadClient

from taskloop.discussion import DiscussionComment, DiscussionSource
from taskloop.task import TaskBinding, TaskInspection, TaskInspectionError
from taskloop.tracker import CommentsRead, inspect_task, task_comments


class DiscussionRead(TaskReadClient, CommentsRead, Protocol):
    """Only structured task and comment reads."""


def read_discussion(task: TaskInspection, binding: TaskBinding, client: DiscussionRead) -> tuple[DiscussionSource, ...]:
    links: dict[str, set[str]] = {task.reference.task_id: {"task itself"}}
    for link in task.dependencies:
        if link.reference.scope != binding.scope:
            raise TaskInspectionError("invalid_binding", f"Linked discussion {link.reference.task_id} is outside the configured backlog")
        if link.reference != task.reference:
            links.setdefault(link.reference.task_id, set()).add(link.relationship)
    sources = []
    for task_id in sorted(links):
        try:
            found = task if task_id == task.reference.task_id else inspect_task(binding, client, task_id)
            comments = task_comments(client, task_id)
            sources.append(DiscussionSource(task_id=task_id, title=found.title, relationships=tuple(sorted(links[task_id])),
                                            comments=tuple(DiscussionComment(author=c.author, at=c.at, text=c.text) for c in comments)))
        except TaskInspectionError as error:
            raise TaskInspectionError(error.kind, f"Discussion source {task_id}: {error}") from error
    return tuple(sources)
