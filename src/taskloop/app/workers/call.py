"""One AI step in flight: its prompts, thread and counters, which change between its delegate calls."""
from typing import Any

from tlkernel.asked import Updates
from tlkernel.delegateport import Answer

from taskloop.app.workers import call_state as callstate
from taskloop.app.workers import worker_identity


class Call:
    def __init__(
        self,
        node: str,
        role: str,
        schema: dict[str, Any],
        cwd: Any,
        full: str,
        text: str,
        delta: str | None,
        key: tuple[Any, ...],
        thread: str,
        step: str | None,
        title: str,
    ) -> None:
        self.node, self.role, self.schema, self.cwd, self.full, self.text = node, role, schema, cwd, full, text
        self.delta, self.key, self.thread = delta, key, thread
        self.step, self.title, self.visual = step, title, False
        self.boundary = False
        self.tries = 1  # calls that came back with no valid answer, from 1: two at most (RetryPlan invalid_output)
        self.counts: dict[str, float] = {"attempt": 0}  # Ctx's counters
        self.denied_retried = False
        self.secret_fp = False  # the last denial was a `secrets` stop on a heredoc body that merely names .env
        self.finished: Answer | None = None  # an answer the last run left on disk
        self.state: callstate.CallState | None = None
        self.prepared: worker_identity.PreparedCall | None = None
        self.sha = ""
        self.updates = Updates()  # what the last valid answer said about the writer's thread (asked.thread_updates)
        self.limit_s: float | None = None  # the --timeout the last call was given
