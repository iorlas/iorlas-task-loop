"""The run collaborators declared by its fields and initialized by the engine."""
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.checks.runner import Checker
from taskloop.app.pipeline.budget import Budget
from taskloop.app.pipeline.steps import Steps
from taskloop.app.workers.calls import Calls


class FieldParts:
    steps: Steps
    budget: Budget
    calls: Calls
    checklog: CheckLog
    checker: Checker
