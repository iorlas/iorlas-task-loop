"""The run collaborators declared by its fields and initialized by the engine."""
from tlgate.checklog import CheckLog
from tlgate.runner import Checker
from tlpipeline.api import Budget, Steps

from taskloop.app.workers.calls import Calls


class FieldParts:
    steps: Steps
    budget: Budget
    calls: Calls
    checklog: CheckLog
    checker: Checker
