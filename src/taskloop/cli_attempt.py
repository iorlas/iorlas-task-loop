"""The `attempt` command surface: `show`, `list`, `setup-times` and `export`, the factory's reads of its attempts (read-only)."""

import argparse
from collections.abc import Callable

from taskloop import attempt_export, attempt_status, cli_composition, setup_timing
from taskloop.attempt_export_store import ExportStore
from taskloop.cli_common import ARTIFACTS, DB, Parsers, add, backlog, backlog_of, common, group, views_for
from taskloop.machine_config import Loaded
from taskloop.operations import Failed
from taskloop.result_data import Result
from taskloop.setup_store import SetupStore

GROUP = "attempt"


def register(commands: Parsers) -> None:
    verbs = group(commands, GROUP, "Read the factory's attempts (read-only)")
    status = add(verbs, "show", "A task as the factory holds it: its attempt, entry, setup run, result and next action (read-only; "
                 "`tl task show` reads the tracker)")
    status.add_argument("task_id", metavar="TASK")
    status.add_argument("--backlog", metavar="KEY", help="Task scope; defaults to the machine config's backlog, then the sole backlog "
                        "in factory.db")
    common(status, DB, ARTIFACTS)
    listing = add(verbs, "list", "Every task's current attempt with its next action (read-only)")
    listing.add_argument("--stuck", action="store_true", help="Only attempts whose next action is stuck:*, hold or unknown")
    common(listing, DB, ARTIFACTS)
    timing = add(verbs, "setup-times", "Recent persisted implement setup times (read-only; no decision)")
    backlog(timing)
    common(timing, DB)
    export = add(verbs, "export", "One row per agent attempt for A/A and A/B comparison, CSV with a header (NULL empty; --json: an array "
                 "of objects, NULL as null; read-only). Pool only rows with the same engine_digest and workflow_digest")
    export.add_argument("--backlog", metavar="KEY", help="Only this backlog (default: the machine config's backlog, else every backlog)")
    common(export, DB)


def _show(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        if isinstance(reads, Failed):
            return reads
        return attempt_status.show_attempt(reads, loaded.settings.artifacts.value, arguments.backlog, arguments.task_id,
                                           configured_backlog=loaded.settings.backlog.value)


def _list(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        return reads if isinstance(reads, Failed) else attempt_status.list_attempts(reads, stuck=arguments.stuck)


def _setup_times(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        if isinstance(reads, Failed):
            return reads
        return setup_timing.report(SetupStore(reads.store.connect, reads.store.begin), backlog_of(arguments, loaded))


def _export(arguments: argparse.Namespace, loaded: Loaded) -> Result:
    with cli_composition.open_reads(loaded.settings.db.value, loaded.settings.artifacts.value, views_for(loaded)) as reads:
        if isinstance(reads, Failed):
            return reads
        found = arguments.backlog or loaded.settings.backlog.value
        return attempt_export.export(ExportStore(reads.store.connect, reads.store.begin), found)


OPERATIONS: dict[tuple[str, str], Callable[[argparse.Namespace, Loaded], Result]] = {
    (GROUP, "show"): _show,
    (GROUP, "list"): _list,
    (GROUP, "setup-times"): _setup_times,
    (GROUP, "export"): _export,
}
