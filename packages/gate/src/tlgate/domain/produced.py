"""Executable outputs identifiable from earlier check argv, without running a build or guessing by a bin directory alone."""
import os
from collections.abc import Sequence
from pathlib import PurePosixPath

from tlgate.domain.cmd.matchers import head


def option(argv: Sequence[str], *names: str) -> str:
    """The last explicit value of an output, configuration or framework option."""
    value = ""
    for n, word in enumerate(argv):
        if word in names and n + 1 < len(argv):
            value = argv[n + 1]
        elif any(word.startswith(name + "=") for name in names):
            value = word.split("=", 1)[1]
    return value


def produces(argv: Sequence[str], path: str) -> bool:
    """Match a compiler's explicit output, or dotnet build's project-named executable at its output location."""
    args = head(argv)
    if not args:
        return False
    output = option(args, "-o", "--output")
    if os.path.basename(args[0]) in {"cc", "gcc", "clang", "c++", "g++", "clang++", "rustc", "go"}:
        return bool(output and os.path.normpath(output) == os.path.normpath(path))
    if os.path.basename(args[0]) != "dotnet" or args[1:2] != ["build"]:
        return False
    return _dotnet(args, path, output)


def _dotnet(args: Sequence[str], path: str, output: str) -> bool:
    project = next((p for p in args[2:] if p.endswith(".csproj")), "")
    if not project:
        return False
    source, target = PurePosixPath(project), PurePosixPath(os.path.normpath(path))
    if target.name != source.stem:
        return False
    if output:
        return target.parent == PurePosixPath(os.path.normpath(output))
    config = option(args, "-c", "--configuration") or "Debug"
    framework = option(args, "-f", "--framework")
    folder = source.parent / "bin" / config
    return (target.parent.parent == folder and target.parent.name.startswith("net")
            and (not framework or target.parent.name == framework))
