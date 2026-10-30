"""PathProbe: the questions the plan-check lint asks of a tree, answered by PATH, just and the file system (a TreeProbe)."""
import json
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from taskloop.contracts import env as penv

WORD_TTL_S = 120.0  # a tool installed since is found within two minutes
JUSTFILES = ("justfile", "Justfile", ".justfile")


class PathProbe:
    def __init__(self, wt: str | Path, env: Mapping[str, str] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.wt = Path(wt)
        self.env = dict(penv.snapshot().vars if env is None else env)
        self.clock = clock
        self.words: dict[str, tuple[bool, float]] = {}
        self.justfile: tuple[int, set[str] | None] | None = None

    def has_command(self, word: str) -> bool:
        """True when `word` resolves to an executable on the PATH a check will see (the worktree's env), shutil.which."""
        known = self.words.get(word)
        if known is None or self.clock() - known[1] > WORD_TTL_S:
            known = (shutil.which(word, path=self.env.get("PATH")) is not None, self.clock())
            self.words[word] = known
        return known[0]

    def recipes(self) -> set[str] | None:
        """The recipe and alias names of the justfile (`just --dump --dump-format json`), private ones too; cached by the
        justfile's modification time: a rebase or an edit shows."""
        jf = next((self.wt / n for n in JUSTFILES if (self.wt / n).is_file()), None)
        if jf is None:
            return None
        stamp = jf.stat().st_mtime_ns
        if self.justfile and self.justfile[0] == stamp:
            return self.justfile[1]
        names: set[str] | None = None
        try:
            r = subprocess.run(["just", "--dump", "--dump-format", "json"], capture_output=True, check=False, text=True,
                               cwd=str(self.wt), timeout=20, env=self.env)
            if r.returncode == 0:
                d = json.loads(r.stdout)
                names = set(d.get("recipes") or {}) | set(d.get("aliases") or {})
        except (OSError, subprocess.SubprocessError, ValueError):
            names = None
        self.justfile = (stamp, names)
        return names

    def exists(self, path: str) -> bool:
        return (self.wt / path).exists()

    def is_dir(self, path: str) -> bool:
        return (self.wt / path).is_dir()
