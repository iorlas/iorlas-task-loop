"""The root `tl drain` surface; no task, tracker, checkout or model is required."""

import argparse
import json
import sys
import time

from taskloop import drain_evidence
from taskloop.cli_composition import load_config
from taskloop.drain.composition import open_drain
from taskloop.drain.drain import drain
from taskloop.drain.models import Conclusion, Result
from taskloop.drain.render import data, human
from taskloop.exit_codes import ExitCode
from taskloop.inspection_guide import CONFIG
from taskloop.machine_config import ConfigRefused, Flags


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "drain",
        help="Block new work, let existing executions finish, and verify idle",
        allow_abbrev=False,
        description="Block new work, let existing executions finish, and verify the factory idle, before an upgrade or restart. "
        "Writes a durable drain request in factory.db; schedules, signals and releases nothing. Retrying observes the same "
        "request. A completed drain stays in force until `tl rounds start` is started again under matching code, which reopens it.",
    )
    parser.add_argument("--db", metavar="PATH", help="Existing compatible factory.db (overrides machine config)")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Print structured progress and final result")


def run(arguments: argparse.Namespace) -> int:
    def report(result: Result) -> None:
        print(json.dumps(data(result)) if arguments.json_output else human(result), flush=True)

    loaded = load_config(arguments.config, Flags(db=arguments.db))
    if isinstance(loaded, ConfigRefused):
        result = Result(conclusion=Conclusion.REFUSED, detail=f"Machine configuration refused: {loaded.reason}: {loaded.detail}")
    else:
        with open_drain(loaded.settings.db.value, report) as opened:
            result = opened if isinstance(opened, Result) else drain(opened)
    failed = result.conclusion not in {Conclusion.WAITING, Conclusion.COMPLETE}
    text = human(result) + (f"\n{CONFIG[loaded.reason]}" if isinstance(loaded, ConfigRefused) else "")
    shown = data(result)
    if result.conclusion is Conclusion.COMPLETE and not isinstance(loaded, ConfigRefused):
        saved = drain_evidence.save(loaded, time.time())
        text += f"\nAttempt export {saved}"
        shown |= {"export": saved}
    print(json.dumps(shown) if arguments.json_output else text, file=sys.stderr if failed else sys.stdout)
    return {Conclusion.COMPLETE: ExitCode.SUCCESS, Conclusion.REFUSED: ExitCode.REFUSED, Conclusion.INTERRUPTED: ExitCode.INTERRUPTED}.get(
        result.conclusion, ExitCode.UNKNOWN
    )
