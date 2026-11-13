"""Command line. Imports only the standard library and the git port until a run is needed (a no-op run stays cheap)."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from docscheck.gitport import ChangedPaths, changed_paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docscheck")
    parser.add_argument("command", choices=["check", "generate"], nargs="?", default="check")
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--all", action="store_true", help="check every doc; never run automatically")
    parser.add_argument("--base", default="main", help="the ref changes are measured from (merge-base)")
    parser.add_argument("--keys", action="store_true", help="print each finding's waiver key")
    parser.add_argument("--changed", type=Path, nargs="*", default=None, help="explicit changed paths instead of asking Git")
    return parser


def gate(changed: Sequence[Path], folders: Sequence[Path]) -> bool:
    """True when some changed path lies under a folder the checker reads."""
    return any(path.is_relative_to(folder) for path in changed for folder in folders)


def main(argv: Sequence[str] | None = None, ask: ChangedPaths = changed_paths) -> int:
    args = _parser().parse_args(argv)
    docs, ontology, repo = args.docs.resolve(), args.ontology.resolve(), args.repo.resolve() if args.repo else None
    package = Path(__file__).resolve().parent
    if args.command == "check" and not args.all:
        changed = [path.resolve() for path in args.changed] if args.changed is not None else ask(docs, args.base)
        watched = [docs, ontology, package, *([repo / "src", repo / "tests"] if repo else [])]
        if not gate(changed, watched):
            print("skipped: nothing changed that the docs depend on")
            return 0
    else:
        changed = []
    from docscheck.main import execute  # heavy imports start here

    return execute(args.command, docs, ontology, repo, changed, full=args.all or args.command == "generate", package=package, keys=args.keys)
