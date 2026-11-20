"""The root `tl workflow` surface: `show` reads a workflow file from Git, `init` writes a starter into the working tree."""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.exit_codes import ExitCode
from taskloop.git_views import GitProfileFiles, GitViews
from taskloop.input_context import InputError
from taskloop.inspection_guide import UNAVAILABLE, WORKFLOW, WORKFLOW_INIT
from taskloop.printable import block, one_line
from taskloop.workflow import Agent, Section, StepTable
from taskloop.workflow_read import DEFAULT, Pin, WorkflowRefusal, plain_name, read_workflow
from taskloop.workflow_starter import Created, Writer, create_new, scaffold

SHOW: Final = "show"
INIT: Final = "init"
KIND: Final = "kind"
MESSAGE: Final = "message"
NAME: Final = "name"
EXISTS: Final = "exists"
UNWRITABLE: Final = "unwritable"
ABSENT: Final = "machine config"
PREVIEW: Final = 60
NEW_FILE: Final = (
    "The file is new and uncommitted. Tasks read the workflow from the commit they start from, so it has to be committed "
    "to the branch the tasks start from before a task can use it."
)


def _file_name(value: str) -> str:
    if not plain_name(value):
        raise argparse.ArgumentTypeError("a plain file name of lowercase letters, digits, '-' and '_'")
    return value


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow = commands.add_parser(
        "workflow", help="The workflow file .task-loop/workflows/NAME.toml: inspect it, scaffold one", allow_abbrev=False
    )
    operations = workflow.add_subparsers(dest="operation", required=True)
    show = operations.add_parser(
        SHOW,
        help="Print a workflow as the factory reads it from Git at --at (read-only)",
        allow_abbrev=False,
        description="Print the workflow file `.task-loop/workflows/NAME.toml` as the factory reads it from Git at --at: its digest, "
        "each step's agent choice and ordered prompt sections, and the feedback section count. Reads Git only; writes nothing.",
    )
    show.add_argument("--at", default="HEAD", metavar="REV", help="The commit to read (default: HEAD)")
    init = operations.add_parser(
        INIT,
        help="Write a starter workflow file into the working tree, uncommitted",
        allow_abbrev=False,
        description="Write a generic starter workflow `.task-loop/workflows/NAME.toml` into the checkout's working tree, creating "
        "its folders. The file is left uncommitted: nothing is staged or committed and the profile is untouched. An existing "
        "file is refused and never overwritten.",
    )
    for parser in (show, init):
        parser.add_argument("--checkout", default=".", metavar="PATH", help="The repository checkout (default: .)")
        parser.add_argument(
            "--name", default=DEFAULT, metavar="NAME", type=_file_name, help=f"The workflow file name without .toml (default: {DEFAULT})"
        )
        parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


def _agent(agent: Agent) -> dict[str, object]:
    return {"harness": agent.harness, "model": agent.model, "effort": agent.effort, "compaction_token_limit": agent.compaction_token_limit}


def _section(section: Section) -> dict[str, str]:
    if section.use is not None:
        return {KIND: "renderer", NAME: str(section.use)}
    return {KIND: "text", "start": one_line(section.text or "", PREVIEW)}


def _table(table: StepTable) -> dict[str, object]:
    return {"agent": _agent(table.agent), "prompt": [_section(each) for each in table.prompt]}


def _data(pin: Pin, name: str, at: str) -> dict[str, object]:
    return {
        NAME: name,
        "at": at,
        "sha": pin.sha,
        "digest": pin.digest,
        "steps": {"plan": _table(pin.workflow.step.plan), "implement": _table(pin.workflow.step.implement)},
        "feedback_sections": len(pin.workflow.step.feedback),
    }


def _step_lines(step: str, table: StepTable) -> list[str]:
    lines = [f"Step {step}"]
    lines += [f"  {key}: {ABSENT if value is None else value}" for key, value in _agent(table.agent).items()]
    for number, each in enumerate(_section(each) for each in table.prompt):
        lines.append(f"  prompt {number + 1}: " + (f'text "{each["start"]}"' if each[KIND] == "text" else f"renderer {each[NAME]}"))
    return lines


def _lines(pin: Pin, name: str, at: str) -> list[str]:
    steps = pin.workflow.step
    return [
        f"Workflow {name} at {at}",
        f"Digest: {pin.digest}",
        f"Read at: {pin.sha}",
        *_step_lines("plan", steps.plan),
        *_step_lines("implement", steps.implement),
        f"Feedback sections: {len(steps.feedback)}",
    ]


def _fail(arguments: argparse.Namespace, label: str, error: dict[str, str], guide: str, code: ExitCode) -> int:
    print(
        json.dumps({"error": error}) if arguments.json_output else f"tl workflow {label}: {block(error[MESSAGE])}\n{guide}", file=sys.stderr
    )
    return code


def show(arguments: argparse.Namespace) -> int:
    checkout = Path(arguments.checkout).expanduser().absolute()
    files = GitProfileFiles(checkout, GitViews(DEFAULT_GIT_READ_SECONDS).checkouts)
    try:
        pin = read_workflow(files, arguments.at, arguments.name)
    except WorkflowRefusal as refusal:
        found = refusal.refused
        error = {KIND: str(found.reason), "where": found.where, MESSAGE: str(refusal)}
        return _fail(arguments, SHOW, error, WORKFLOW[found.reason], ExitCode.REFUSED)
    except InputError as unavailable:
        return _fail(arguments, SHOW, {KIND: UNAVAILABLE, MESSAGE: str(unavailable)}, WORKFLOW[UNAVAILABLE], ExitCode.UNKNOWN)
    print(
        json.dumps(_data(pin, arguments.name, arguments.at))
        if arguments.json_output
        else "\n".join(_lines(pin, arguments.name, arguments.at))
    )
    return ExitCode.SUCCESS


def init(arguments: argparse.Namespace, write: Writer = create_new) -> int:
    checkout = Path(arguments.checkout).expanduser().absolute()
    try:
        if not checkout.is_dir():
            raise NotADirectoryError(str(checkout))
        outcome = scaffold(checkout, arguments.name, write)
    except OSError as error:
        message = f"{checkout} cannot be written: {error.strerror or error}"
        return _fail(arguments, INIT, {KIND: UNWRITABLE, MESSAGE: message}, WORKFLOW_INIT[UNWRITABLE], ExitCode.REFUSED)
    if not isinstance(outcome, Created):
        message = f"A workflow file already exists at {outcome.path}"
        return _fail(arguments, INIT, {KIND: EXISTS, MESSAGE: message}, WORKFLOW_INIT[EXISTS], ExitCode.REFUSED)
    print(json.dumps({"path": str(outcome.path), "committed": False}) if arguments.json_output else f"Wrote {outcome.path}\n{NEW_FILE}")
    return ExitCode.SUCCESS


def run(arguments: argparse.Namespace) -> int:
    return show(arguments) if arguments.operation == SHOW else init(arguments)
