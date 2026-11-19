"""The parser helpers every command group shares: the flags, the group and the Git views."""

import argparse

from taskloop.git_views import GitViews
from taskloop.machine_config import Loaded

type Parsers = argparse._SubParsersAction[argparse.ArgumentParser]
DB, ARTIFACTS = "--db", "--artifacts"  # flags shared by many commands
PATH = "PATH"  # the metavar of a flag that takes a file or directory


def common(parser: argparse.ArgumentParser, *flags: str) -> None:
    helps = {
        DB: (PATH, "factory.db (overrides the machine config)"),
        ARTIFACTS: ("DIR", "Artifacts root (overrides the machine config)"),
        "--root": ("DIR", "Slots root (overrides the machine config's slots_root)"),
    }
    for flag in flags:
        parser.add_argument(flag, metavar=helps[flag][0], help=helps[flag][1])
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON data; refusals are JSON on stderr")


def backlog(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--backlog", metavar="KEY", required=required, help="The tracker backlog (key) the task belongs to")


def add(parsers: Parsers, name: str, text: str) -> argparse.ArgumentParser:
    return parsers.add_parser(name, help=text, description=text, allow_abbrev=False)


def group(commands: Parsers, name: str, text: str) -> Parsers:
    return add(commands, name, text).add_subparsers(dest="operation", required=True)


def views_for(loaded: Loaded) -> GitViews:
    """The real Git views, bounded by the machine config's `git_read_seconds`."""
    return GitViews(loaded.settings.git_read_seconds.value)
