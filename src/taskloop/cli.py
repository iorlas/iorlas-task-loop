"""Present the supported task-loop command surface."""

import argparse
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import asdict
from importlib.metadata import version as package_version
from pathlib import Path

from git_porcelain import GitReadFailure, GitTimeout, GitUnavailable, NotARepo

from taskloop import cli_step
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.git_views import GitProfileFiles, GitViews
from taskloop.land_summary import block, one_line
from taskloop.profile import Refused, Resolved, Unavailable, resolve
from taskloop.repo import UnsupportedCheckout
from taskloop.step_guide import STEP_ONLY
from taskloop.task import TaskInspectionError
from taskloop.tracker_client import inspect_tracker_task, tracker_located


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
        shown = {key: value for key, value in asdict(result).items() if key not in {"status", "assignee"}}  # its keys as they were
        print(json.dumps(shown))
    else:
        scope = result.reference.scope
        print(f"Task: {one_line(result.reference.task_id, 200)}\nBacklog: {one_line(f'{scope.adapter}/{scope.backlog}', 200)}")
        print(f"Title: {one_line(result.title, 500)}")
        print(f"Requirements:\n{block(result.requirements)}\nAcceptance:\n{block(result.acceptance)}")
        print("Dependencies:")
        for dependency in result.dependencies:
            name, status = one_line(dependency.reference.task_id, 200), one_line(dependency.status, 40)
            print(f"  {one_line(dependency.relationship, 40)}: {name} ({status}) {one_line(dependency.title, 500)}")
    return 0


def _profile_data(found: Resolved, at: str, target_ref: str) -> dict[str, object]:
    return {
        "at": at, "target_ref": target_ref, "setup": [list(argv) for argv in found.setup],
        "checks": [{"name": check.name, "argv": list(check.argv), "timeout": check.timeout} for check in found.checks],
        "required": list(found.required), "target": found.target,
    }


def _profile_lines(found: Resolved, at: str, target_ref: str) -> list[str]:
    lines = [f"Profile: setup and checks at {at}; required and target from {target_ref}"]
    lines += [f"Setup: {shlex.join(argv)}" for argv in found.setup] or ["Setup: (none)"]
    lines += [f"Check {check.name}: {shlex.join(check.argv)} (timeout {check.timeout} s)" for check in found.checks] or [
        "Checks: (none)"]
    return [*lines, f"Required: {', '.join(found.required) or '(none)'}", f"Target: {found.target}"]


def show_profile(arguments: argparse.Namespace) -> int:
    """The resolved profile; exit 1 for a refusal (its fixed reason word), 3 when Git could not be read."""
    checkout = Path(arguments.checkout).expanduser().absolute()
    found = resolve(GitProfileFiles(checkout, GitViews(DEFAULT_GIT_READ_SECONDS).checkouts), arguments.at, arguments.target)
    match found:
        case Resolved():
            data, lines = _profile_data(found, arguments.at, arguments.target), _profile_lines(found, arguments.at, arguments.target)
            print(json.dumps(data) if arguments.json_output else "\n".join(lines))
            return 0
        case Refused(reason=reason, side=side, key=key, detail=detail):
            error: dict[str, str] = {"kind": reason, "side": side, "key": key, "message": detail}
            text = f"tl profile show: refused {reason} ({side}{', ' + key if key else ''}): {detail}"
            code = 1
        case Unavailable(detail=detail):
            error, text, code = {"kind": "unavailable", "message": detail}, f"tl profile show: unavailable: {detail}", 3
    print(json.dumps({"error": error}) if arguments.json_output else text, file=sys.stderr)
    return code


def show_version(arguments: argparse.Namespace) -> int:
    """`tl version [--json]`: the version of the package this process runs."""
    found = package_version("iorlas-task-loop")
    print(json.dumps({"version": found}) if arguments.json_output else found)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Present implemented commands and render truthful inspection failures."""
    tracker_located()  # before any bd call: the given tracker root decides the tracker, never an inherited BEADS_DIR
    parser = argparse.ArgumentParser(
        prog="tl",
        description=f"Task-loop successor foundation. Step commands ({STEP_ONLY}).",
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
    profile = commands.add_parser("profile", help="The repository profile .task-loop.json, read from Git", allow_abbrev=False)
    profile_show = profile.add_subparsers(dest="operation", required=True).add_parser(
        "show", help="Print the resolved profile: setup and checks at --at, required and target from --target (read-only)",
        allow_abbrev=False)
    profile_show.add_argument("--checkout", default=".", metavar="PATH", help="The repository checkout (default: .)")
    profile_show.add_argument("--at", default="HEAD", metavar="REV", help="The commit under test (default: HEAD)")
    profile_show.add_argument("--target", default="main", metavar="REF", help="The target ref holding required and target "
                              "(default: main)")
    profile_show.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")
    cli_step.register(commands)
    commands.add_parser("version", help="Print the running package version", allow_abbrev=False).add_argument(
        "--json", action="store_true", dest="json_output")
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
    if arguments.command in cli_step.COMMANDS:
        return cli_step.run(arguments)
    handlers = {"repo": inspect_repo, "task": show_task, "profile": show_profile, "version": show_version}
    return handlers[arguments.command](arguments)


def inspect_repo(arguments: argparse.Namespace) -> int:
    """`tl repo inspect PATH`: the checkout's repository identity (read-only)."""
    try:
        result = GitViews(DEFAULT_GIT_READ_SECONDS).inspect_checkout(arguments.path)
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
