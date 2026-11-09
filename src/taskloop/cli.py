"""Present the supported task-loop command surface."""

import argparse
import json
import sys
from collections.abc import Sequence

from git_porcelain import GitReadFailure, GitTimeout, GitUnavailable, NotARepo

from taskloop.composition import inspect_checkout
from taskloop.repo import UnsupportedCheckout


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


def main(argv: Sequence[str] | None = None) -> int:
    """Present implemented commands and render truthful inspection failures."""
    parser = argparse.ArgumentParser(
        prog="tl",
        description="Task-loop successor foundation. Task execution commands are not available yet.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command")
    repo = commands.add_parser("repo", help="Inspect a local repository", allow_abbrev=False)
    operations = repo.add_subparsers(dest="operation", required=True)
    inspect = operations.add_parser("inspect", help="Inspect an explicit checkout root (readonly)", allow_abbrev=False)
    inspect.add_argument("path", metavar="PATH", help="Explicit checkout root; subdirectories, files and bare repositories are unsupported")
    inspect.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0
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
