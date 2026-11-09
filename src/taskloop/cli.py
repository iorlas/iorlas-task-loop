"""Present the supported task-loop command surface."""

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Show help and reject requests for commands that are not implemented."""
    parser = argparse.ArgumentParser(
        prog="tl",
        description="Task-loop successor foundation. Task execution commands are not available yet.",
        allow_abbrev=False,
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0
