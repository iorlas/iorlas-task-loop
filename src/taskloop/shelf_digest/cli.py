"""Read-only digest generation, independent of tracker or factory configuration."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from git_porcelain import GitUnavailable

from taskloop.git_views import GitViews
from taskloop.shelf_digest.generate import Digest, generate_installed_digest
from taskloop.shelf_digest.installed import InstalledDistributions
from taskloop.shelf_digest.render import render_digest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m taskloop.shelf_digest", allow_abbrev=False)
    parser.add_argument("--checkout", type=Path, default=Path("."), metavar="PATH", help="Task-loop checkout (default: .)")
    parser.add_argument("--at", default="HEAD", metavar="REV", help="Task-loop revision (default: HEAD)")
    arguments = parser.parse_args(argv)
    try:
        views = GitViews(30)
        result = generate_installed_digest(views.checkouts(arguments.checkout.expanduser().resolve()), arguments.at,
                                           InstalledDistributions())
        if not isinstance(result, Digest):
            print(result.explanation, file=sys.stderr)
            return 1
        output = render_digest(result)
    except (GitUnavailable, OSError, RuntimeError, ValueError, TypeError) as error:
        print(f"Cannot generate shelf digest: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(output)
    return 0
