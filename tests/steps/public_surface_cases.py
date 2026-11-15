"""CLI JSON examples through real parsing/rendering and fake owning operations."""

from collections.abc import Callable
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Never

import pytest
from public_surface_fixtures import LOADED, PATH, ROUND_FLAGS, step_cases
from pydantic import JsonValue, TypeAdapter

from taskloop import cli, cli_composition, cli_drain, cli_step, dash_composition
from taskloop.drain.models import Action, ActionKind, Conclusion, Identity, Owner, Result, Role
from taskloop.operations import Ended
from taskloop.profile import Check, Refused, Resolved, Unavailable
from taskloop.repo import RepoId, RepoInspection, UnsupportedCheckout
from taskloop.task import TaskDependency, TaskInspection, TaskInspectionError, TaskReference, TaskScope

JSON = TypeAdapter(JsonValue)


def capture(argv: list[str]) -> dict[str, object]:
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = cli.main([*argv, "--json"])
        except SystemExit as error:
            raise AssertionError(f"CLI case rejected {argv}: {stderr.getvalue()}") from error
    return {"argv": argv, "exit": code,
            "stdout": [JSON.validate_json(line) for line in stdout.getvalue().splitlines()],
            "stderr": [JSON.validate_json(line) for line in stderr.getvalue().splitlines()]}


def raising(error: Exception) -> Callable[..., Never]:
    def fail(*_args: object, **_kwargs: object) -> Never:
        raise error
    return fail


@dataclass
class RepoViews:
    result: RepoInspection
    checkouts: object = None

    def inspect_checkout(self, _path: str) -> RepoInspection:
        return self.result


def inspections(patch: pytest.MonkeyPatch) -> dict[str, object]:
    cases: dict[str, object] = {}
    patch.setattr(cli, "package_version", lambda _name: "1.2.3")  # installed version is intentionally volatile
    cases["version"] = capture(["version"])
    for configured in (False, True):
        repo = RepoInspection(RepoId("repo"), PATH / "git", PATH, "https://example.test/repo" if configured else None)
        patch.setattr(cli, "GitViews", lambda _seconds, repo=repo: RepoViews(repo))
        cases[f"repo.origin.{configured}"] = capture(["repo", "inspect", str(PATH)])
    patch.setattr(cli, "GitViews", raising(UnsupportedCheckout("Unsupported checkout")))
    cases["repo.refused"] = capture(["repo", "inspect", str(PATH)])
    reference = TaskReference(TaskScope("tasks"), "tl-1")
    dependency = TaskDependency(TaskReference(reference.scope, "tl-2"), "blocks", "Dependency", "open")
    argv = ["task", "show", "tl-1", "--backlog", "tasks", "--tracker-root", "/tracker"]
    for dependencies in ((), (dependency,)):
        task = TaskInspection(reference, "Task", "Requirements", "Acceptance", dependencies, "open", "owner")
        patch.setattr(cli, "inspect_tracker_task", lambda *_args, task=task: task)
        cases[f"task.dependencies.{len(dependencies)}"] = capture(argv)
    for linked in (False, True):
        error = TaskInspectionError("not_found", "Task unavailable", reference=reference if linked else None,
                                    backend_kind="missing" if linked else None)
        patch.setattr(cli, "inspect_tracker_task", raising(error))
        cases[f"task.refused.{linked}"] = capture(argv)
    patch.setattr(cli, "GitViews", lambda _seconds: RepoViews(repo))
    patch.setattr(cli, "GitProfileFiles", lambda *_args: None)
    for name, profile in {
        "empty": Resolved((), (), (), "main"),
        "full": Resolved((("just", "install"),), (Check("test", ("just", "test"), 60),), ("test",), "main"),
        "refused": Refused("unknown_key", "engine", "Unknown profile key"),
        "unavailable": Unavailable("Git unavailable"),
    }.items():
        patch.setattr(cli, "resolve", lambda *_args, profile=profile: profile)
        cases[f"profile.{name}"] = capture(["profile", "show", "--checkout", str(PATH)])
    return cases


def steps(patch: pytest.MonkeyPatch) -> dict[str, object]:
    cases: dict[str, object] = {}
    patch.setattr(cli_composition, "load_config", lambda *_args: LOADED)
    for name, (argv, result) in step_cases().items():
        with patch.context() as operation:
            operation.setitem(cli_step.OPERATIONS, (argv[0], argv[1]), lambda *_args, result=result: result)
            cases[name] = capture(argv)
    # Keep the real rounds start rendering; fake only its IO and scheduling operation.
    patch.setattr(cli_step, "views_for", lambda _loaded: None)
    patch.setattr(cli_composition, "open_rounds", lambda *_args: nullcontext(RoundFacts()))
    patch.setattr(dash_composition, "serving", lambda *_args: nullcontext(None))
    patch.setattr(cli_step, "run_rounds", lambda *_args: Ended("tasks", "interrupted"))
    cases["rounds.start-end"] = capture(["step", "rounds", "--backlog", "tasks", "--no-dashboard", *ROUND_FLAGS])
    return cases


@dataclass(frozen=True)
class RoundFacts:
    ctrl_c: bool = True


def drain_cases(patch: pytest.MonkeyPatch) -> dict[str, object]:
    cases: dict[str, object] = {}
    identity = Identity(pid=7, pgid=7, start="process-start", boot="boot")
    owner = Owner(subject="attempt", role=Role.ENTRY, identity=identity)
    action = Action(action_id="action", kind=ActionKind.DISPATCH, owner=identity, subject="attempt")
    waiting = Result(conclusion=Conclusion.WAITING, generation=1, active=(owner,), uncertain=(owner,), actions=(action,))
    patch.setattr(cli_drain, "load_config", lambda *_args: LOADED)

    def opened(_path: Path, report: Callable[[Result], None]) -> object:
        report(waiting)
        return nullcontext(final)

    patch.setattr(cli_drain, "open_drain", opened)
    for conclusion in Conclusion:
        final = Result(conclusion=conclusion, generation=1, detail="Drain result")
        cases[f"drain.{conclusion.value}"] = capture(["drain"])
    return cases


def cli_cases() -> dict[str, object]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cli, "tracker_located", lambda: None)
        return inspections(patch) | steps(patch) | drain_cases(patch)
