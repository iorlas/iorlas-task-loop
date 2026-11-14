"""Factory-owned committed context; renderers receive values, never perform I/O."""

from dataclasses import dataclass
from shlex import join

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


@dataclass(frozen=True)
class InputContext:
    commit: str
    commands: tuple[str, ...]
    glossary: str

    def render(self) -> str:
        commands = "\n".join(f"- {command}" for command in self.commands) or "(none)"
        return f"{BEGIN}\n{ORIENTATION}\nSource commit: {self.commit}\nCheck commands:\n{commands}\n\n{self.glossary}{END}"


def read(files: ProfileFiles, commit: str) -> InputContext:
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
    return InputContext(commit, tuple(join(check.argv) for check in profile.checks), glossary)


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
