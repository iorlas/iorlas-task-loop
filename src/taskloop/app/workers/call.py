"""One AI step in flight: its prompts, thread and counters, which change between its delegate calls."""
from typing import Any

from tlkernel.asked import Updates
from tlkernel.delegateport import Answer

from taskloop.app.workers import worker_identity
from taskloop.stores import call_state as callstate


class Call:
    def __init__(
        self,
        node: str,
        role: str,
        schema: dict[str, Any],
        cwd: Any,
        full: str,
        text: str,
        writer: str | None,
        resume: str | None,
        key: tuple[Any, ...],
        resume_key: bool,
        writer_family: str | None,
        step: str | None,
        title: str,
    ) -> None:
        self.node, self.role, self.schema, self.cwd, self.full, self.text = node, role, schema, cwd, full, text
        self.writer, self.resume, self.key, self.resume_key, self.writer_family = writer, resume or None, key, resume_key, writer_family
        self.step, self.title, self.visual = step, title, False
        self.tries = 1  # calls that came back with no valid answer, from 1: two at most (RetryPlan invalid_output)
        self.counts: dict[str, float] = {"attempt": 0, "polls": 0, "crashes": 0, "resume_refused": 0,
                                         "waited_lane_s": 0.0, "waited_net_s": 0.0}  # Ctx's counters
        self.denied_retried = False
        self.secret_fp = False  # the last denial was a `secrets` stop on a heredoc body that merely names .env
        self.was_resumed = bool(resume)
        self.out_on = ""  # the lane that went out under this step (the writer's fallback lane)
        self.up_now: bool | None = None  # the network probe at the last network stop
        self.finished: Answer | None = None  # an answer the last run left on disk
        self.state: callstate.CallState | None = None
        self.prepared: worker_identity.PreparedCall | None = None
        self.sha = ""
        self.thread = Updates()  # what the last valid answer said about the writer's thread (asked.thread_updates)
        self.limit_s: float | None = None  # the --timeout the last call was given
