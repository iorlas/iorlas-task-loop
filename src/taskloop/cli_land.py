"""The `land` command surface: `run`, `show` and `withdraw`, parsers and the one land call; every decision is `land.land`'s."""

import argparse
from collections.abc import Callable

from taskloop import cli_composition, land
from taskloop.cli_common import ARTIFACTS, DB, Parsers, add, backlog, backlog_of, checkout, checkout_of, common, group, views_for
from taskloop.land import Mode
from taskloop.land_guide import INTERRUPTED
from taskloop.machine_config import Loaded
from taskloop.operations import Failed
from taskloop.result_data import Result

GROUP = "land"
WITHDRAW = "withdraw"
MODES: dict[str, Mode] = {"run": "land", "show": "summary", WITHDRAW: "withdraw"}  # subcommand -> the operation's mode
READS = {
    "show": "Print the land summary, the facts to read before landing; records, reserves, pushes and closes nothing",
    WITHDRAW: "Give up a validated, undelivered candidate (origin read first, nothing pushed) so the task can be abandoned",
}
RUN = ("Land the task's checked commit X yourself: fetch origin's main (O), squash X onto it as one commit S (Git objects only), "
       "run every check again on S in a free slot, in this shell, only when main moved or its required names changed, push S "
       "to origin's main as you (never forced), then close the task in your local tracker (never synced: `bd dolt push` is "
       "yours). A rerun does only what is missing; under the profile's `land: auto` a round runs this same land by itself. "
       "Your checkout and local main are never written. Exit 0 landed "
       "(or already), 1 refused, 3 unknown (a rerun is safe), 130 interrupted by Ctrl-C (a rerun reconciles it)")


def _task(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", metavar="TASK")
    backlog(parser)
    checkout(parser, "Your checkout of the repository: its origin is fetched and pushed")
    common(parser, DB, ARTIFACTS)


def register(commands: Parsers) -> None:
    verbs = group(commands, GROUP, "Land a checked task on origin's main (run), read the facts first (show), or give up a candidate")
    run = add(verbs, "run", RUN)
    _task(run)
    run.add_argument("--minutes", type=int, help="Deadline of the validation of S, from now; needed when S must be validated (main "
                     "moved or its required names changed) or a pending candidate resumes; not for --no-change or a same-tree land")
    run.add_argument("--no-change", action="store_true", help="Accept that origin's main already holds X's changes: "
                     "recorded and closed with no push")
    run.add_argument("--accept-gate-changes", action="store_true", help="Accept that S changes what decides a pass (a check's "
                     "argv, timeout, setup or required names, a configuration file, a weakened test): without it the land "
                     "refuses and lists them")
    for name, text in READS.items():
        _task(add(verbs, name, text))


def _land(mode: Mode) -> Callable[[argparse.Namespace, Loaded], Result]:
    def operation(arguments: argparse.Namespace, loaded: Loaded) -> Result:
        """The one land; a `KeyboardInterrupt` (Ctrl-C) anywhere in it is `unavailable:interrupted`, exit 130: the land's own
        unwinding already stopped a running check's tree, and the rerun reconciles what is left (as the rounds' abrupt stop)."""
        request = land.LandRequest(backlog_of(arguments, loaded), arguments.task_id, checkout_of(arguments, loaded),
                                   getattr(arguments, "minutes", None), mode, getattr(arguments, "no_change", False),
                                   getattr(arguments, "accept_gate_changes", False))
        try:
            with cli_composition.open_land(loaded.settings.db.value, loaded.settings.artifacts.value,
                                           views_for(loaded)) as ports:
                return ports if isinstance(ports, Failed) else land.land(ports, request)
        except KeyboardInterrupt:
            return Failed("unavailable", INTERRUPTED)

    return operation


OPERATIONS: dict[tuple[str, str], Callable[[argparse.Namespace, Loaded], Result]] = {
    (GROUP, name): _land(mode) for name, mode in MODES.items()
}
