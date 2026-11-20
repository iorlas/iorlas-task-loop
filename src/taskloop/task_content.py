"""Canonical evidence of task requirements and retained tracker discussion."""

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from taskloop.task import TaskInspection

if TYPE_CHECKING:
    from taskloop.discussion import DiscussionSource


class TaskContentDigest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


class CommentContent(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    author: str
    at: str
    text: str


class SourceContent(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    task_id: str
    title: str
    relationships: tuple[str, ...]
    comments: tuple[CommentContent, ...]


class TaskContent(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    backlog: str
    task_id: str
    title: str
    requirements: str
    acceptance: str
    sources: tuple[SourceContent, ...]


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical(content: BaseModel) -> str:
    return json.dumps(content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(task: TaskInspection, sources: tuple[DiscussionSource, ...]) -> TaskContentDigest:
    retained = tuple(SourceContent(
        task_id=normalized(source.task_id), title=normalized(source.title),
        relationships=tuple(sorted({normalized(each) for each in source.relationships})),
        comments=tuple(CommentContent(author=normalized(comment.author), at=normalized(comment.at), text=normalized(comment.text))
                       for comment in source.comments if not comment.generated),
    ) for source in sources)
    content = TaskContent(
        backlog=normalized(task.reference.scope.backlog), task_id=normalized(task.reference.task_id),
        title=normalized(task.title), requirements=normalized(task.requirements), acceptance=normalized(task.acceptance),
        sources=tuple(sorted(retained, key=canonical)),
    )
    return TaskContentDigest(value=hashlib.sha256(canonical(content).encode("utf-8")).hexdigest())
