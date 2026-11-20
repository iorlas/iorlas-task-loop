"""`tl init`: write the starter profile and workflow file a repository lacks, into the working tree, uncommitted."""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from taskloop.cli_workflow import file_name
from taskloop.exit_codes import ExitCode
from taskloop.init_files import Writer, create_new, scaffold
from taskloop.printable import block
from taskloop.workflow_read import DEFAULT

COMMAND: Final = "init"
UNWRITABLE: Final = "unwritable"
UNCOMMITTED: Final = (
    "The files are new and uncommitted. Tasks read both from the commit they start from, so commit them to the branch the "
    "tasks start from. Name the checks the repository's gate runs in `checks` and `required` before a task can pass."
)


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init = commands.add_parser(
        COMMAND,
        help="Write the starter profile and workflow file the repository lacks, uncommitted",
        allow_abbrev=False,
        description="Write `.task-loop.json` (the repository's gate: setup, checks, required, target, land) and the workflow file "
        "`.task-loop/workflows/NAME.toml` (the prompts and agent choice) into the checkout's working tree, whichever is absent, "
        "creating folders. Nothing is staged or committed, and a file that exists is never overwritten. Run it again with another "
        "--workflow NAME to add a second workflow for an A/B arm.",
    )
    init.add_argument("--checkout", default=".", metavar="PATH", help="The repository checkout (default: .)")
    init.add_argument(
        "--workflow", default=DEFAULT, metavar="NAME", type=file_name, help=f"The workflow file name without .toml (default: {DEFAULT})"
    )
    init.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


def run(arguments: argparse.Namespace, write: Writer = create_new) -> int:
    checkout = Path(arguments.checkout).expanduser().absolute()
    try:
        if not checkout.is_dir():
            raise NotADirectoryError(str(checkout))
        outcome = scaffold(checkout, arguments.workflow, write)
    except OSError as error:
        message = f"{checkout} cannot be written: {error.strerror or error}"
        print(
            json.dumps({"error": {"kind": UNWRITABLE, "message": message}})
            if arguments.json_output
            else f"tl init: {block(message)}\nCheck that the checkout exists and that its folders can be written.",
            file=sys.stderr,
        )
        return ExitCode.REFUSED
    if arguments.json_output:
        created, kept = [str(each) for each in outcome.created], [str(each) for each in outcome.kept]
        print(json.dumps({"created": created, "kept": kept, "committed": False}))
        return ExitCode.SUCCESS
    lines = [f"Wrote {each}" for each in outcome.created] + [f"Kept {each}: it already exists" for each in outcome.kept]
    print("\n".join(lines + ([UNCOMMITTED] if outcome.created else [])))
    return ExitCode.SUCCESS
