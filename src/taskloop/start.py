"""The `tl` console script: resolve the owner pin once, before the CLI is imported, then replace this process (one exec).

`python -I -m taskloop` (`__main__`) is the exec's target and never resolves, so one start resolves exactly once
(tl-8bh9.8.3 section 5). This is the factory's only `os.execv` (policy test); it imports the standard library, `installs`
and `pin_file` only (import contract `start-decides-before-the-cli`). Nothing is opened, locked or printed before the
decision; a refusal prints one line on stderr and changes nothing.
"""

import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from taskloop import pin_file
from taskloop.installs import LocalFiles, Reads, installs_root, python_of, state
from taskloop.pin_file import PinInvalid

EXEMPT: Final = frozenset({"install", "pin", "version"})  # they manage installs: they run where they are started
type Replace = Callable[[str, list[str]], NoReturn]  # `os.execv`


@dataclass(frozen=True)
class Scan:
    """What the pre-scan reads of argv: the top-level `--config` and the command word (None: none, or help first)."""

    config: str | None
    command: str | None


@dataclass(frozen=True)
class Exec:
    python: str
    args: tuple[str, ...]  # argv after the program name, unchanged

    def argv(self) -> list[str]:
        return [self.python, "-I", "-m", "taskloop", *self.args]


@dataclass(frozen=True)
class PinRefused:
    word: str  # `pin:invalid`, `pin:missing`, `pin:incomplete`, `pin:broken`; `pin:exec` is unavailable
    commit: str | None
    message: str


def scan(args: Sequence[str]) -> Scan:
    """Left to right: `--config` takes the next token whatever it is, `--config=FILE` its value, `-h`/`--help` stop with
    no command word; the first other token is the command word."""
    config: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--config":
            config = args[index + 1] if index + 1 < len(args) else None
            index += 2
        elif token.startswith("--config="):
            config = token.removeprefix("--config=")
            index += 1
        else:
            return Scan(config, None if token in {"-h", "--help"} else token)
    return Scan(config, None)


def _named(commit: str, tag: str | None) -> str:
    return commit[:12] if tag is None else f"{commit[:12]} ({tag})"


def resolve(args: Sequence[str], home: Path, executable: str, files: Reads) -> Exec | PinRefused:
    """The one resolver: an exempt command or no pin runs the started install (`executable`); a pin runs its complete
    install; anything else refuses. No version comparison, no listing, no fallback, no Git, no factory.db."""
    found, own = scan(args), Exec(executable, tuple(args))
    if found.command is None or found.command in EXEMPT:
        return own
    path = pin_file.pin_path(found.config, home)
    pin = pin_file.nameless(found.config) if path is None else pin_file.read(files, path)
    if pin is None:
        return own
    if isinstance(pin, PinInvalid):
        where = "" if path is None else f"the pin file {path} is invalid: "
        return PinRefused("pin:invalid", None, f"{where}{pin.detail}; tl pin REV, or tl pin --clear")
    root, named = installs_root(home), _named(pin.commit, pin.tag)
    install, rev = root / pin.commit, pin.tag or pin.commit
    found_state = state(files, root, pin.commit)
    match found_state.word:
        case "absent":
            text = f"pinned {named} is not installed under {root}; tl install {rev} --checkout PATH, or tl pin --clear"
        case "incomplete":
            text = (f"pinned {named} at {install} has no manifest (an install never finished, or is still building); "
                    "wait for it, or tl pin --clear")
        case "broken":
            text = (f"pinned {named} at {install} is broken ({found_state.detail}); move it aside and tl install {rev} "
                    "--checkout PATH, or tl pin --clear")
        case "complete":
            return Exec(str(python_of(install)), tuple(args))
    return PinRefused(f"pin:{'missing' if found_state.word == 'absent' else found_state.word}", pin.commit, text)


def _refuse(refused: PinRefused, json_output: bool, kind: str = "refused") -> None:
    error = {"kind": refused.word, "commit": refused.commit, "message": refused.message}
    print(json.dumps({"error": error}) if json_output else f"tl: {kind} {refused.word}: {refused.message}", file=sys.stderr)


def run(argv: Sequence[str], home: Path, executable: str, files: Reads, replace: Replace) -> int:
    """Refuse (exit 1) or replace this process with `<python> -I -m taskloop <argv[1:]>`; 3 when the exec fails."""
    args = list(argv[1:])
    decided = resolve(args, home, executable, files)
    if isinstance(decided, PinRefused):
        _refuse(decided, "--json" in args)
        return 1
    try:
        replace(decided.python, decided.argv())
    except OSError as error:
        _refuse(PinRefused("pin:exec", None, f"cannot run {decided.python}: {error}"), "--json" in args, "unavailable")
        return 3


def main() -> int:
    """The console script `tl`: this process's argv, home and interpreter."""
    return run(sys.argv, Path.home(), sys.executable, LocalFiles(), os.execv)
