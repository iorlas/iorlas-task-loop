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
    CODEX = "codex"
    PYTHON = "python"
    TAILWIND = "tailwind"


class Prerequisites(BaseModel):
    git_version: Version


class ManagedTools(BaseModel):
    python: Version
    codex: Version = Field(alias="aqua:openai/codex")
    tailwind: Version = Field(alias="aqua:tailwindlabs/tailwindcss")


class Configuration(BaseModel):
    vars: Prerequisites
    tools: ManagedTools


class LockedTool(BaseModel):
    version: str
    backend: str


class Lock(BaseModel):
    tools: dict[str, list[LockedTool]]


BACKENDS = {
    Tool.CODEX: "aqua:openai/codex",
    Tool.PYTHON: "python",
    Tool.TAILWIND: "aqua:tailwindlabs/tailwindcss",
}
LOCK_BACKENDS = {**BACKENDS, Tool.PYTHON: "core:python"}
PATTERNS = {
    Tool.GIT: r"git version (\d+\.\d+\.\d+)",
    Tool.CODEX: r"codex-cli (\d+\.\d+\.\d+)",
    Tool.PYTHON: r"Python (\d+\.\d+\.\d+)",
    Tool.TAILWIND: r"≈ tailwindcss v(\d+\.\d+\.\d+)",
}


def check(root: Path, probes: dict[Tool, str]) -> tuple[str, ...]:
    config = Configuration.model_validate(tomllib.loads((root / "mise.toml").read_text()))
    lock = Lock.model_validate(tomllib.loads((root / "mise.lock").read_text()))
    expected = {
        Tool.GIT: config.vars.git_version,
        Tool.CODEX: config.tools.codex,
        Tool.PYTHON: config.tools.python,
        Tool.TAILWIND: config.tools.tailwind,
    }
    errors: list[str] = []
    for tool, pin in expected.items():
        output = probes.get(tool, "").strip()
        # Tailwind's documented help starts with its version, followed by usage.
        version_line = output.splitlines()[0] if tool == Tool.TAILWIND and output else output
        match = re.fullmatch(PATTERNS[tool], version_line)
        if match is None or match[1] != pin or "probe failed" in output:
            errors.append(f"{tool}: expected {pin}; executable reported {output!r}")
        if tool in BACKENDS:
            backend = BACKENDS[tool]
            entries = lock.tools.get(backend, [])
            if len(entries) != 1 or entries[0].version != pin or entries[0].backend != LOCK_BACKENDS[tool]:
                errors.append(f"{tool}: expected {pin}; mise.lock declares {entries!r}")
    selector = (root / ".python-version").read_text().strip()
    if selector != expected[Tool.PYTHON]:
        errors.append(f"python: expected {expected[Tool.PYTHON]}; .python-version declares {selector!r}")
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
