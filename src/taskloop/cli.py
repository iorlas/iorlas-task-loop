"""Present the supported task-loop command surface."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from git_porcelain import GitReadFailure, GitTimeout, GitUnavailable, NotARepo

from taskloop import cli_plan
from taskloop.composition import inspect_checkout, inspect_tracker_task, tracker_located
from taskloop.repo import UnsupportedCheckout
from taskloop.task import TaskInspectionError


def inspection_error_kind(error: GitUnavailable | UnsupportedCheckout | OSError) -> str:
    """Project supported refusal types into stable CLI error kinds."""
    match error:
        case NotARepo():
            return "not_a_repo"
        case GitReadFailure():
            return "git_read_failure"
        case GitTimeout():
            return "git_timeout"
        case GitUnavailable():
            return "git_unavailable"
        case UnsupportedCheckout():
            return "unsupported_checkout"
        case OSError():
            return "path_unavailable"


def show_task(arguments: argparse.Namespace) -> int:
    """Render the same scoped task inspection in human or structured form."""
    try:
        result = inspect_tracker_task(arguments.task_id, arguments.backlog, arguments.tracker_root)
    except TaskInspectionError as error:
        if arguments.json_output:
            data: dict[str, object] = {"kind": error.kind, "message": str(error)}
            if error.reference is not None:
                data["reference"] = asdict(error.reference)
            if error.backend_kind is not None:
                data["backend_kind"] = error.backend_kind
            print(json.dumps({"error": data}), file=sys.stderr)
        else:
            print(f"tl task show: {error}", file=sys.stderr)
        return 1
    if arguments.json_output:
        print(json.dumps(asdict(result)))
    else:
        scope = result.reference.scope
        print(f"Task: {result.reference.task_id}\nBacklog: {scope.adapter}/{scope.backlog}\nTitle: {result.title}")
        print(f"Requirements:\n{result.requirements}\nAcceptance:\n{result.acceptance}")
        print("Dependencies:")
        for dependency in result.dependencies:
            print(f"  {dependency.relationship}: {dependency.reference.task_id} ({dependency.status}) {dependency.title}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Present implemented commands and render truthful inspection failures."""
    tracker_located()  # before any bd call: the given tracker root decides the tracker, never an inherited BEADS_DIR
    parser = argparse.ArgumentParser(
        prog="tl",
        description=f"Task-loop successor foundation. Plan commands run the {cli_plan.PLAN_ONLY}.",
        allow_abbrev=False,
    )
    parser.add_argument("--config", metavar="FILE", help="Machine config file (default ~/.config/task-loop/config.toml)")
    commands = parser.add_subparsers(dest="command")
    repo = commands.add_parser("repo", help="Inspect a local repository", allow_abbrev=False)
    operations = repo.add_subparsers(dest="operation", required=True)
    inspect = operations.add_parser("inspect", help="Inspect an explicit checkout root (readonly)", allow_abbrev=False)
    inspect.add_argument("path", metavar="PATH", help="Explicit checkout root; subdirectories, files and bare repositories are unsupported")
    inspect.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")
    task = commands.add_parser("task", help="Read a task in an explicitly configured backlog", allow_abbrev=False)
    task_operations = task.add_subparsers(dest="operation", required=True)
    show = task_operations.add_parser("show", help="Inspect a task without modifying the tracker", allow_abbrev=False)
    show.add_argument("task_id", metavar="TASK_ID")
    show.add_argument("--backlog", required=True, help="Explicit logical backlog key; no identity is inferred")
    show.add_argument("--tracker-root", required=True, help="Explicit directory for the configured tracker")
    show.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")
    cli_plan.register(commands)
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    if arguments.command in cli_plan.COMMANDS:
        return cli_plan.run(arguments)
    if arguments.command == "task":
        return show_task(arguments)
    try:
        result = inspect_checkout(arguments.path)
    except (GitUnavailable, UnsupportedCheckout, OSError) as error:
        if arguments.json_output:
            print(json.dumps({"error": {"kind": inspection_error_kind(error), "message": str(error)}}), file=sys.stderr)
        else:
            print(f"tl repo inspect: {error}", file=sys.stderr)
        return 1
    data = {
        "repo_id": result.repo_id,
        "common_dir": str(result.common_dir),
        "checkout_path": str(result.checkout_path),
        "origin_url": result.origin_url,
    }
    if arguments.json_output:
        print(json.dumps(data))
    else:
        print(f"Repo ID: {result.repo_id}\nCommon directory: {result.common_dir}\nCheckout: {result.checkout_path}")
        print(f"Origin: {result.origin_url if result.origin_url is not None else '(not configured)'}")
    return 0
