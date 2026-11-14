"""Factory-owned committed context; renderers receive values, never perform I/O."""

import tomllib
from dataclasses import dataclass
from shlex import join
from typing import Protocol

from pydantic import AliasPath, BaseModel, Field

from taskloop import glossary_extract
from taskloop.profile import NoCommit, NotAFile, Profile, ProfileFiles, Unavailable, read_profile

BEGIN = "BEGIN FACTORY INPUT CONTEXT"
END = "END FACTORY INPUT CONTEXT"
ORIENTATION = (
    "AGENTS.md is already in context: follow it without reading it again. These attempt-specific directions replace "
    "its general orientation-file read instructions. The supplied task text is the complete task specification. "
    "You have no task tracker: bd and the beads skill are unavailable. Do not invoke bd (including bd prime or bd show) "
    "or load the beads SKILL.md. Do not search git log with the task id as a grep pattern: it supplies no further spec. "
    "Do not read the justfile or .task-loop.json: the check commands below replace instructions to read those files. Listing checks "
    "does not require a plan attempt to run implementation checks. Use the included glossary definitions; read the full "
    "glossary only for missing terms, collected into at most one targeted read command per attempt. Do not start by "
    "reading it in full. Read the task's own plan as this step requires; read an older foundation plan only if the task's "
    "own plan cites it. If no glossary exists at the source commit, do not search for one."
)


class InputError(Exception):
    """A committed input could not be constructed; its explanation prevents dispatch."""


class InputFiles(ProfileFiles, Protocol):
    def paths(self, commit: str) -> tuple[str, ...] | NoCommit | Unavailable:
        """Tracked repository-relative names at the commit, never working-tree paths."""
        ...


class _PytestSettings(BaseModel):
    pythonpath: tuple[str, ...] = Field(default=(), validation_alias=AliasPath("tool", "pytest", "ini_options", "pythonpath"))
    addopts: str | tuple[str, ...] = Field(default="", validation_alias=AliasPath("tool", "pytest", "ini_options", "addopts"))


@dataclass(frozen=True)
class InputContext:
    commit: str
    commands: tuple[str, ...]
    glossary: str
    paths: tuple[str, ...]
    layout: str = ""

    def render(self) -> str:
        commands = "\n".join(f"- {command}" for command in self.commands) or "(none)"
        names = "\n".join(self.paths) or "(no tracked paths under src/, tests/ or docs/design/)"
        return (f"{BEGIN}\n{ORIENTATION}\nSource commit: {self.commit}\nCheck commands:\n{commands}\n\n"
                f"{self.glossary}\nCODE MAP\n{self.layout}{names}\n{END}")


def read(files: InputFiles, commit: str) -> InputContext:
    profile = read_profile(files, commit)
    if not isinstance(profile, Profile):
        raise InputError(f"Profile at {commit}: {profile.detail}")
    blob = files.blob(commit, glossary_extract.PATH)
    match blob:
        case None:
            glossary = "No docs/glossary.md exists at this commit; no glossary definitions are supplied.\n"
        case bytes():
            try:
                glossary = glossary_extract.extract(blob)
            except ValueError as error:
                raise InputError(f"Glossary at {commit}: {error}") from error
        case Unavailable(detail=detail):
            raise InputError(f"Glossary at {commit}: {detail}")
        case NotAFile(mode=mode):
            raise InputError(f"Glossary at {commit} is not a regular file (mode {mode})")
        case NoCommit():
            raise InputError(f"Glossary source {commit} names no commit")
    names = files.paths(commit)
    if isinstance(names, Unavailable):
        raise InputError(f"Code map at {commit}: {names.detail}")
    if isinstance(names, NoCommit):
        raise InputError(f"Code map source {commit} names no commit")
    paths = tuple(sorted(path for path in names if path.startswith(("src/", "tests/", "docs/design/"))))
    return InputContext(commit, tuple(join(check.argv) for check in profile.checks), glossary, paths, _layout(files, commit, names))


def _layout(files: InputFiles, commit: str, names: tuple[str, ...]) -> str:
    """Only describe taskloop layout and helper imports established by this committed tree."""
    if not any(path.startswith("src/taskloop/") and path.count("/") == 2 and path.endswith(".py") for path in names):
        return ""
    hints = ["In this repository, source modules are primarily src/taskloop/*.py."]
    folders = tuple(folder for folder in ("agents", "drain", "check_repeat", "dash")
                    if any(path.startswith(f"src/taskloop/{folder}/") for path in names))
    if folders:
        hints.append("Feature subfolders: " + ", ".join(f"src/taskloop/{folder}/" for folder in folders) + ".")
    tests = tuple(folder for folder in ("steps", "cli", "rules") if any(path.startswith(f"tests/{folder}/") for path in names))
    if tests:
        hints.append("Tests: " + ", ".join(f"tests/{folder}/" for folder in tests) + ".")
    if "tests/steps/doubles.py" in names and "pyproject.toml" in names:
        blob = files.blob(commit, "pyproject.toml")
        if not isinstance(blob, bytes):
            raise InputError(f"Code map pytest configuration at {commit}: {blob}")
        try:
            config = _PytestSettings.model_validate(tomllib.loads(blob.decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as error:
            raise InputError(f"Code map pytest configuration at {commit}: {error}") from error
        options = config.addopts.split() if isinstance(config.addopts, str) else config.addopts
        if config.pythonpath == ("tests/steps",) and "--import-mode=importlib" in options:
            hints.append('Shared test helpers such as doubles.py live in tests/steps; committed pytest settings use '
                         'importlib mode and pythonpath = ["tests/steps"].')
    return "\n".join(hints) + "\n"


def refresh(text: str, context: InputContext) -> str:
    """Replace the factory's delimited block, including inside repeat frames, exactly once."""
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == BEGIN]
    ends = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == END]
    if not starts and not ends:
        return text + "\n\n" + context.render() + "\n"
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise InputError("Input has malformed or duplicate factory context")
    lines[starts[0]:ends[0] + 1] = [context.render() + "\n"]
    return "".join(lines)
