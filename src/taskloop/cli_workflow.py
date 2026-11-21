"""The root `tl workflow` surface: `show` reads a workflow file from Git."""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.exit_codes import ExitCode
from taskloop.git_views import GitProfileFiles, GitViews
from taskloop.input_context import InputError
from taskloop.inspection_guide import UNAVAILABLE, WORKFLOW
from taskloop.printable import block, one_line
from taskloop.workflow import Agent, Section, StepTable
from taskloop.workflow_read import DEFAULT, Pin, WorkflowRefusal, plain_name, read_workflow

SHOW: Final = "show"
KIND: Final = "kind"
MESSAGE: Final = "message"
NAME: Final = "name"
ABSENT: Final = "machine config"
PREVIEW: Final = 60


def file_name(value: str) -> str:
    if not plain_name(value):
        raise argparse.ArgumentTypeError("a plain file name of lowercase letters, digits, '-' and '_'")
    return value


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow = commands.add_parser("workflow", help="The workflow file .task-loop/workflows/NAME.toml: inspect it", allow_abbrev=False)
    operations = workflow.add_subparsers(dest="operation", required=True)
    show = operations.add_parser(
        SHOW,
        help="Print a workflow as the factory reads it from Git at --at (read-only)",
        allow_abbrev=False,
        description="Print the workflow file `.task-loop/workflows/NAME.toml` as the factory reads it from Git at --at: its digest, "
        "each step's agent choice and ordered prompt sections, and the feedback sections. Reads Git only; writes nothing.",
    )
    show.add_argument("--at", default="HEAD", metavar="REV", help="The commit to read (default: HEAD)")
    show.add_argument("--checkout", default=".", metavar="PATH", help="The repository checkout (default: .)")
    show.add_argument(
        "--name", default=DEFAULT, metavar="NAME", type=file_name, help=f"The workflow file name without .toml (default: {DEFAULT})"
    )
    show.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


def _agent(agent: Agent) -> dict[str, object]:
    return {"harness": agent.harness, "model": agent.model, "effort": agent.effort, "compaction_token_limit": agent.compaction_token_limit}


def _section(section: Section) -> dict[str, str]:
    if section.use is not None:
        return {KIND: "renderer", NAME: str(section.use)}
    return {KIND: "text", "start": one_line(section.text or "", PREVIEW)}


def _cap(pin: Pin) -> dict[str, object]:
    return {"max_attempts": pin.workflow.implement_cap}


def _table(table: StepTable) -> dict[str, object]:
    return {"agent": _agent(table.agent), "prompt": [_section(each) for each in table.prompt]}


def _data(pin: Pin, name: str, at: str) -> dict[str, object]:
    return {
        NAME: name,
        "at": at,
        "sha": pin.sha,
        "digest": pin.digest,
        "steps": {"plan": _table(pin.workflow.step.plan), "implement": _table(pin.workflow.step.implement) | _cap(pin)},
        "feedback_sections": len(pin.workflow.step.feedback),
        "feedback": [_section(each) for each in pin.workflow.step.feedback],
    }


def _step_lines(step: str, table: StepTable) -> list[str]:
    lines = [f"Step {step}"]
    lines += [f"  {key}: {ABSENT if value is None else value}" for key, value in _agent(table.agent).items()]
    lines += _section_lines("prompt", table.prompt)
    return lines


def _section_lines(label: str, sections: tuple[Section, ...]) -> list[str]:
    return [
        f"  {label} {number + 1}: " + (f'text "{each["start"]}"' if each[KIND] == "text" else f"renderer {each[NAME]}")
        for number, each in enumerate(_section(each) for each in sections)
    ]


def _lines(pin: Pin, name: str, at: str) -> list[str]:
    steps = pin.workflow.step
    return [
        f"Workflow {name} at {at}",
        f"Digest: {pin.digest}",
        f"Read at: {pin.sha}",
        *_step_lines("plan", steps.plan),
        *_step_lines("implement", steps.implement),
        f"  max_attempts: {pin.workflow.implement_cap}",
        f"Feedback sections: {len(steps.feedback)}",
        *_section_lines("feedback", steps.feedback),
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


def run(arguments: argparse.Namespace) -> int:
    return show(arguments)
