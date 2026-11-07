"""What `tl doctor` says of a repo against tl's layout (tl-9un.32) and of the factory leaking into it (tl-9un.37): one line per place,
read-only (nothing is removed or rewritten), and no line for a compliant repo. Repo-type neutral: it knows the layout tl sets (the
artifact dir, the scratch folder), never what a repo builds."""
import re
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath

from tlkernel.config import CheckSpec, RepoProfile
from tlkernel.paths import TASK_EXCLUDE

ARTIFACT = "TL_ARTIFACT_DIR"
OUTPUT_FLAG = re.compile(r"^-{1,2}[A-Za-z-]*(log|out|report|result|xml)[A-Za-z-]*$", re.IGNORECASE)
FACTORY_NAME = re.compile(r"\b(TL_[A-Z0-9_]+|TASK_LOOP_[A-Z0-9_]+)\b")
FACTORY_WORDING = re.compile(r"task[- ]loop", re.IGNORECASE)
PROFILE = ".task-loop.json"
PROSE = frozenset({".md", ".txt", ".rst"})
STAMP = re.compile(r"(\.stamp|[-_.]green|^gate[-_.]ok)$", re.IGNORECASE)
READ_CAP = 200_000


def _outside(spec: CheckSpec) -> list[str]:
    """The paths a check's argv names as its output (a flag about logs, outputs, reports or results) that are not under the artifact dir."""
    out: list[str] = []
    argv = spec.argv
    for i, word in enumerate(argv):
        flag, eq, value = word.partition("=")
        if OUTPUT_FLAG.match(flag):
            value = value if eq else (argv[i + 1] if i + 1 < len(argv) else "")
            if value and not value.startswith("-") and ARTIFACT not in value:
                out.append(value)
    return out


def deviations(profile: RepoProfile) -> list[str]:
    """Each place the profile's checks leave tl's layout: output outside the artifact dir, a keep glob that leaves the tree, and (one
    line) checks that never use the artifact dir at all, which is the repo not having opted in."""
    checks = profile.engine.checks
    lines: list[str] = []
    for c in checks:
        for path in _outside(c):
            lines.append(f"check {c.id}: writes {path} outside ${ARTIFACT}; tl collects, rotates and shows what is under ${ARTIFACT}")
        lines += [f"check {c.id}: keep glob {g} leaves the tree; keep takes tree-relative globs" for g in c.keep
                  if g.startswith(("/", "..", "~"))]
    if checks and not any(ARTIFACT in " ".join(c.argv) or ARTIFACT in c.env.values() for c in checks):
        lines.append(f"no check uses ${ARTIFACT}: the repo has not opted into tl's layout; checks write their results there")
    return lines


def _tool(path: str) -> bool:
    return path != PROFILE and PurePosixPath(path).suffix.lower() not in PROSE


def leaks(paths: Sequence[str], read: Callable[[str], str]) -> list[str]:
    """One line per tracked file that carries the factory: a scratch-folder file, a journal, a stamp, or a tool that names TL_ variables or
    tl. `read` gives a file's text ("" when it cannot be read). Nothing is changed."""
    lines: list[str] = []
    for path in paths:
        name = PurePosixPath(path).name
        if path.startswith(TASK_EXCLUDE):
            lines.append(f"{path}: tl's scratch folder is tracked ({TASK_EXCLUDE} belongs in .git/info/exclude)")
        elif name.lower().startswith("journal"):
            lines.append(f"{path}: a journal file, the factory's record; the repo keeps its own history in git")
        elif STAMP.search(name):
            lines.append(f"{path}: a stamp of its own; tl keeps the facts of a green gate (tl check)")
        elif _tool(path):
            text = read(path)[:READ_CAP]
            names = sorted(set(FACTORY_NAME.findall(text)))
            found = ([", ".join(names)] if names else []) + (["tl wording"] if FACTORY_WORDING.search(text) else [])
            if found:
                lines.append(f"{path}: names the factory ({'; '.join(found)}); a repo's tool should not know it")
    return lines
