"""The git pre-push hook: before a push leaves, ask tl whether each pushed tip is green. Plain python3 and the standard library only
(no msgspec, no record model; .importlinter holds it): it runs in git's hook path and reads the repo's .task-loop.json as plain JSON.

Per pushed tip: green when `tl green STEP --repo DIR --tree T --base B` answers 0 for every gate step. A tip that is not green is
refused, unless it is the checked-out HEAD of a clean worktree: then the plan runs (`tl check`, which stamps what it ran) and tl is
asked again. A lower tip of a stack (an ancestor of another pushed tip) is accepted when that other tip is green, never alone.
The engine's own push carries TL_LAND and passes at once. A repo without a gate step has nothing to ask. Any failure of the hook
itself lets the push go (a broken hook must not hold work back)."""
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

GATE_RUNS = ("gate", "both")
DEFAULT_BASE = "origin/main"
Run = Callable[[list[str], str], tuple[int, str]]


def run(argv: list[str], cwd: str) -> tuple[int, str]:
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    return r.returncode, r.stdout.strip()


def gate_steps(repo: str) -> tuple[list[str], str]:
    """(the ids of the gate checks, the base ref) of the repo's profile; no profile or no gate check: no steps."""
    try:
        engine = json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")).get("engine") or {}
        steps = [str(c["id"]) for c in engine.get("checks") or [] if c.get("run", "stage") in GATE_RUNS]
        return steps, str(engine.get("base") or DEFAULT_BASE)
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return [], DEFAULT_BASE


class PrePush:
    def __init__(self, repo: str, tl: str, sh: Run = run) -> None:
        self.repo, self.tl, self.sh = repo, tl, sh
        self.steps, self.base_ref = gate_steps(repo)

    def git(self, *args: str) -> str:
        return self.sh(["git", *args], self.repo)[1]

    def base_for(self, remote_ref: str, remote_sha: str) -> str:
        """The base a tip was gated on: the base branch's sha (the remote's own value when this push moves that branch)."""
        if remote_ref == "refs/heads/" + self.base_ref.split("/", 1)[-1] and remote_sha.strip("0"):
            return remote_sha
        return self.git("rev-parse", self.base_ref)

    def green(self, sha: str, base: str) -> bool:
        tree = self.git("rev-parse", sha + "^{tree}")
        ask = [self.tl, "green", "{}", "--repo", self.repo, "--tree", tree, "--base", base]
        return bool(tree and base) and all(self.sh([step if a == "{}" else a for a in ask], self.repo)[0] == 0 for step in self.steps)

    def green_or_planned(self, sha: str, base: str) -> bool:
        if self.green(sha, base):
            return True
        if sha == self.git("rev-parse", "HEAD") and not self.git("status", "--porcelain"):
            print(f"tl pre-push: {sha[:12]} is not green: running the plan (tl check)", file=sys.stderr)
            self.sh([self.tl, "check", "--repo", self.repo], self.repo)
            return self.green(sha, base)
        return False

    def judge(self, lines: list[str]) -> list[str]:
        """The refused refs, with the reason."""
        tips = []
        for line in lines:
            parts = line.split()
            if len(parts) == 4 and parts[1].strip("0"):  # a delete (all-zero local sha) pushes no tip
                tips.append((parts[0], parts[1], self.base_for(parts[2], parts[3])))
        stamped = {sha for _, sha, base in tips if self.green_or_planned(sha, base)}
        refused = []
        for ref, sha, _ in tips:
            covered = any(self.sh(["git", "merge-base", "--is-ancestor", sha, top], self.repo)[0] == 0 for top in stamped)
            if sha not in stamped and not covered:
                refused.append(f"{ref} ({sha[:12]}) is not green for {', '.join(self.steps)}; run `tl check` in its worktree, then push")
        return refused


def entry(argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own (remote name, url). Exit 0 lets the push go."""
    if environ.get("TL_LAND") or not argv:
        return 0
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False).stdout.strip()
        hook = PrePush(top, argv[0]) if top else None
        refused = hook.judge(stdin_text.splitlines()) if hook and hook.steps else []
    except (OSError, ValueError):
        return 0
    for why in refused:
        print(f"tl pre-push: refused: {why}", file=sys.stderr)
    return 1 if refused else 0


# The hooks tl's dir answers (git reads core.hooksPath for all of them). Each runs tl's logic where it has any (pre-push), then the
# repo's own hook of the same name, so nothing the repo installed (git-lfs's shim, prek) is skipped by the hooks path tl sets.
STDIN_HOOKS = frozenset({"pre-push", "post-rewrite"})  # git feeds these on stdin (pre-push: the refs); the others get the terminal's


def original_hooks_dir(tl: str, environ: Mapping[str, str]) -> str:
    """The folder the repo's own hooks live in: its core.hooksPath as configured (read without the GIT_CONFIG_* tl injected), else
    <common git dir>/hooks."""
    clean = {k: v for k, v in environ.items() if not k.startswith("GIT_CONFIG_")}
    configured = subprocess.run(["git", "config", "--get", "core.hooksPath"], capture_output=True, text=True, check=False, env=clean)
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=False, env=clean)
    where = configured.stdout.strip() or (str(Path(common.stdout.strip()) / "hooks") if common.stdout.strip() else "")
    mine = Path(tl).resolve().parent.parent / "githooks"
    return "" if not where or Path(where).resolve() == mine else where


def uses_lfs() -> bool:
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False).stdout.strip()
    try:
        return bool(top) and "filter=lfs" in (Path(top) / ".gitattributes").read_text(encoding="utf-8")
    except OSError:
        return False


def githook(name: str, argv: list[str], stdin_text: str, environ: Mapping[str, str]) -> int:
    """argv: the tl command, then git's own arguments for the hook. tl's logic first (pre-push), then the repo's own hook of this name
    with the same arguments and stdin; the first failure's exit code. A repo that uses LFS and has no pre-push hook of its own still
    gets `git lfs pre-push`: a plain `git push` never skips its LFS objects. The engine's push (TL_LAND) has done its own LFS push and
    runs none of this."""
    if environ.get("TL_LAND") or not argv:
        return 0
    tl, args = argv[0], argv[1:]
    if name == "pre-push" and (rc := entry([tl, *args], stdin_text, environ)):
        return rc
    try:
        mine = Path(original_hooks_dir(tl, environ)) / name
        cmd = [str(mine), *args] if mine.is_file() and os_executable(mine) else (
            ["git", "lfs", "pre-push", *args] if name == "pre-push" and uses_lfs() else [])
        if not cmd:
            return 0
        return subprocess.run(cmd, input=stdin_text if name in STDIN_HOOKS else None, text=True, check=False).returncode
    except (OSError, ValueError):
        return 0


def os_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)
