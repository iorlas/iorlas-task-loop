"""The parser helpers every command group shares: the flags, the group and the Git views."""

import argparse
from pathlib import Path

from taskloop.git_views import GitViews
from taskloop.machine_config import (
    ConfigRefused,
    Loaded,
    resolve_backlog,
    resolve_checkout,
    resolve_label,
    resolve_tracker_root,
)

type Parsers = argparse._SubParsersAction[argparse.ArgumentParser]
DB, ARTIFACTS = "--db", "--artifacts"  # flags shared by many commands
PATH = "PATH"  # the metavar of a flag that takes a file or directory


def common(parser: argparse.ArgumentParser, *flags: str) -> None:
    helps = {
        DB: (PATH, "factory.db (overrides the machine config)"),
        ARTIFACTS: ("DIR", "Artifacts root (overrides the machine config)"),
        "--slots-root": ("DIR", "Slots root (overrides the machine config's slots_root)"),
    }
    for flag in flags:
        parser.add_argument(flag, metavar=helps[flag][0], help=helps[flag][1])
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


FROM_CONFIG = "(default: the backlog's entry in the machine config)"  # the help of a flag its backlog's config entry fills


def backlog(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backlog", metavar="KEY", help="The tracker backlog (key) the task belongs to (default: the machine config's backlog)"
    )


def tracker_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tracker-root", metavar=PATH, help=f"The directory of the task tracker (the only writer) {FROM_CONFIG}")


def checkout(parser: argparse.ArgumentParser, text: str = "Your checkout of the repository the tasks change") -> None:
    parser.add_argument("--checkout", metavar=PATH, help=f"{text} {FROM_CONFIG}")


def label(parser: argparse.ArgumentParser, text: str) -> None:
    parser.add_argument("--label", help=f"{text} {FROM_CONFIG}")


class ConfigMissing(Exception):
    """A value neither the flag nor the machine config gives; `cli_step.run` and `show_task` print it as a config refusal."""

    def __init__(self, refused: ConfigRefused) -> None:
        super().__init__(refused.reason)
        self.refused = refused


def need[T](value: T | ConfigRefused) -> T:
    if isinstance(value, ConfigRefused):
        raise ConfigMissing(value)
    return value


def backlog_of(arguments: argparse.Namespace, loaded: Loaded) -> str:
    return need(resolve_backlog(loaded.settings, arguments.backlog))


def tracker_root_of(arguments: argparse.Namespace, loaded: Loaded) -> str:
    return need(resolve_tracker_root(loaded.settings, backlog_of(arguments, loaded), arguments.tracker_root))


def checkout_of(arguments: argparse.Namespace, loaded: Loaded) -> Path:
    return need(resolve_checkout(loaded.settings, backlog_of(arguments, loaded), arguments.checkout))


def label_of(arguments: argparse.Namespace, loaded: Loaded) -> str:
    return need(resolve_label(loaded.settings, backlog_of(arguments, loaded), arguments.label))


def add(parsers: Parsers, name: str, text: str) -> argparse.ArgumentParser:
    return parsers.add_parser(name, help=text, description=text, allow_abbrev=False)


def group(commands: Parsers, name: str, text: str) -> Parsers:
    return add(commands, name, text).add_subparsers(dest="operation", required=True)


def views_for(loaded: Loaded) -> GitViews:
    """The real Git views, bounded by the machine config's `git_read_seconds`."""
    return GitViews(loaded.settings.git_read_seconds.value)
