"""Validate development tool probes and committed declarations; never launch tools."""

import argparse
import re
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError

Version = Annotated[str, Field(strict=True, pattern=r"^\d+\.\d+\.\d+$")]


class Tool(StrEnum):
    GIT = "git"
    PYTHON = "python"
    TAILWIND = "tailwind"


class Prerequisites(BaseModel):
    git_min_version: Version


class ManagedTools(BaseModel):
    tailwind: Version = Field(alias="aqua:tailwindlabs/tailwindcss")


class Configuration(BaseModel):
    vars: Prerequisites
    tools: ManagedTools


class LockedTool(BaseModel):
    version: str
    backend: str


class PythonPin(BaseModel):
    """`.python-version` is the one owner of the interpreter version (uv installs it); mise does not pin Python."""

    python: Version


class Lock(BaseModel):
    tools: dict[str, list[LockedTool]]


BACKENDS = {
    Tool.TAILWIND: "aqua:tailwindlabs/tailwindcss",
}
LOCK_BACKENDS = BACKENDS
PATTERNS = {
    Tool.GIT: r"git version (\d+\.\d+\.\d+)",
    Tool.PYTHON: r"Python (\d+\.\d+\.\d+)",
    Tool.TAILWIND: r"≈ tailwindcss v(\d+\.\d+\.\d+)",
}


def at_least(found: str, floor: str) -> bool:
    return tuple(map(int, found.split("."))) >= tuple(map(int, floor.split(".")))


def check(root: Path, probes: dict[Tool, str]) -> tuple[str, ...]:
    config = Configuration.model_validate(tomllib.loads((root / "mise.toml").read_text()))
    lock = Lock.model_validate(tomllib.loads((root / "mise.lock").read_text()))
    python = PythonPin(python=(root / ".python-version").read_text().strip()).python
    expected = {
        Tool.GIT: config.vars.git_min_version,
        Tool.PYTHON: python,
        Tool.TAILWIND: config.tools.tailwind,
    }
    errors: list[str] = []
    for tool, pin in expected.items():
        output = probes.get(tool, "").strip()
        # Tailwind's documented help starts with its version, followed by usage.
        version_line = output.splitlines()[0] if tool == Tool.TAILWIND and output else output
        match = re.fullmatch(PATTERNS[tool], version_line)
        floor = tool == Tool.GIT
        if match is None or "probe failed" in output or not (at_least(match[1], pin) if floor else match[1] == pin):
            errors.append(f"{tool}: expected {'at least ' if floor else ''}{pin}; executable reported {output!r}")
        if tool in BACKENDS:
            backend = BACKENDS[tool]
            entries = lock.tools.get(backend, [])
            if len(entries) != 1 or entries[0].version != pin or entries[0].backend != LOCK_BACKENDS[tool]:
                errors.append(f"{tool}: expected {pin}; mise.lock declares {entries!r}")
    css = root / "src/taskloop/dash/static/dash.css"
    with css.open() as stylesheet:
        compiler = stylesheet.readline().strip()
    if not compiler.startswith(f"/*! tailwindcss v{expected[Tool.TAILWIND]} |"):
        errors.append(f"tailwind: expected {expected[Tool.TAILWIND]}; dash.css declares {compiler!r}")
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    for tool in Tool:
        parser.add_argument(f"--{tool.value}", required=True)
    arguments = parser.parse_args(argv)
    probes = {tool: str(getattr(arguments, tool.value)) for tool in Tool}
    try:
        errors = check(arguments.root, probes)
    except (OSError, ValueError, ValidationError) as error:
        errors = (f"tool version declarations: {error}",)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
