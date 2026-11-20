"""Task evidence follows requirements and retained decisions, independent of prompt annotations."""

from dataclasses import replace

import pytest
from pydantic import ValidationError
from test_steps import TASK

from taskloop.discussion import DiscussionComment, DiscussionSource, empty
from taskloop.task import TaskInspection
from taskloop.task_content import TaskContentDigest, digest

COMMENT = DiscussionComment(author="owner", at="unknown", text="Décision\nKeep spacing  ")
OWN = DiscussionSource(task_id="tl-1", title="Task", relationships=("task itself",), comments=(COMMENT,))
LINK = DiscussionSource(task_id="tl-2", title="Linked", relationships=("related", "blocks"), comments=(COMMENT,))


def test_canonical_content_normalizes_line_endings_and_source_and_relationship_sets() -> None:
    task = replace(TASK, requirements="one\r\ntwo\rthree", acceptance="done\r\n", title="Title\r")
    comment = COMMENT.model_copy(update={"text": "Décision\r\nKeep spacing  "})
    source = OWN.model_copy(update={"comments": (comment,)})
    reordered = LINK.model_copy(update={"relationships": ("blocks", "related", "blocks")})
    assert digest(task, (source, LINK)) == digest(
        replace(task, requirements="one\ntwo\nthree", acceptance="done\n", title="Title\n"), (reordered, OWN))


@pytest.mark.parametrize("changed", [replace(TASK, title="changed"), replace(TASK, requirements="changed"),
                                     replace(TASK, acceptance="changed")])
def test_task_edits_change_evidence(changed: TaskInspection) -> None:
    assert digest(TASK, (OWN, LINK)) != digest(changed, (OWN, LINK))


@pytest.mark.parametrize("source_index", [0, 1])
@pytest.mark.parametrize("field,value", [("author", "other"), ("at", "2026-11-14T00:00:00Z"), ("text", "New decision")])
def test_retained_own_and_linked_comment_fields_change_evidence(source_index: int, field: str, value: str) -> None:
    sources = [OWN, LINK]
    sources[source_index] = sources[source_index].model_copy(update={"comments": (COMMENT.model_copy(update={field: value}),)})
    assert digest(TASK, (OWN, LINK)) != digest(TASK, tuple(sources))


@pytest.mark.parametrize("field,value", [("task_id", "other"), ("title", "New title"), ("relationships", ("parent-child",))])
def test_discussion_source_fields_change_evidence(field: str, value: object) -> None:
    assert digest(TASK, (OWN, LINK)) != digest(TASK, (OWN, LINK.model_copy(update={field: value})))


def test_comment_order_duplicates_whitespace_and_unicode_are_significant() -> None:
    other = COMMENT.model_copy(update={"text": "second"})
    variants = [(COMMENT,), (COMMENT, COMMENT), (COMMENT, other), (other, COMMENT),
                (COMMENT.model_copy(update={"text": COMMENT.text.rstrip()}),),
                (COMMENT.model_copy(update={"text": "Décision\nKeep spacing  "}),)]
    assert len({digest(TASK, (OWN.model_copy(update={"comments": comments}),)).value for comments in variants}) == len(variants)


def test_generated_comments_are_filtered_but_status_and_assignment_are_not_content() -> None:
    notification = DiscussionComment(author="taskloop", at="later", text="taskloop hold: failed:needs_owner", generated=True)
    assert digest(TASK, (OWN,)) == digest(
        replace(TASK, status="held", assignee="elsewhere"), (OWN.model_copy(update={"comments": (COMMENT, notification)}),))
    assert empty(TASK, "").digest == digest(TASK, ())
    assert empty(TASK, "").digest != empty(replace(TASK, acceptance="new"), "").digest


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_digest_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValidationError):
        TaskContentDigest(value=value)
