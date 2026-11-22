"""Build one arm from the frozen base: a local bare origin named after the repo, a clone, one managed slot, its own tracker with
the task under its fixed id, its own `factory.db`, artifacts and slots, and the neutral `.task-loop.json` every arm shares."""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from stream_proc import Captured

from exp_spec import SLOT_PATH_LIMIT, Run, Spec

Proc = Callable[..., Captured]  # (argv, *, cwd, env, timeout) -> Captured: the one process port, a fake in tests
SETUP_SECONDS = 600.0
IDENTITY = ("-c", "user.name=experiment", "-c", "user.email=experiment@example.com")


class SetupFailed(RuntimeError):
    pass


class Paths:
    """Where one run lives. Nothing is shared between runs except the read-only engine and the empty external tracker."""

    def __init__(self, spec: Spec, run: Run) -> None:
        self.root = spec.work / "runs" / run.name
        self.origin = self.root / f"{spec.repo_name}.git"
        self.repo = self.root / f"{spec.repo_name}-repo"
        self.slots = self.root / "slots"
        self.slot = self.slots / spec.repo_name / "s1"
        self.tracker = self.root / "tracker"
        self.config = self.root / "cfg.toml"
        self.db = self.root / "state" / "factory.db"
        self.artifacts = self.root / "state" / "artifacts"


def empty_tracker(spec: Spec) -> Path:
    """The external tracker the checks see (`BEADS_DIR`): the repo's gate needs a bd database, never this run's."""
    return spec.work / "emptybeads" / ".beads"


def neutral_profile(profile: Mapping[str, object], beads_dir: Path) -> dict[str, object]:
    """The base profile with the neutral wrappers every arm needs: `land: manual` (nothing is ever landed) and every
    check command run under `env BEADS_DIR=<empty external tracker>`."""
    checks = profile.get("checks", [])
    assert isinstance(checks, list)
    wrapped = [{**check, "argv": ["env", f"BEADS_DIR={beads_dir}", *check["argv"]]} for check in checks]
    return {**profile, "checks": wrapped, "land": "manual"}


def config_text(spec: Spec, run: Run, paths: Paths) -> str:
    lines = [f"slot_count = 1\nround_seconds = {spec.round_seconds}\nslots_root = {json.dumps(str(paths.slots))}\n"]
    for step, effort in spec.arms[run.arm].efforts.items():
        lines.append(f"[agents.{step}]\neffort = {json.dumps(effort)}\n")
    return "\n".join(lines)


def tool_env(spec: Spec, *, bd: bool = False) -> dict[str, str]:
    """`tl` and the checks: mise trusts the experiment folder. `bd` calls drop an inherited `BEADS_DIR`, which clashes with `bd init`."""
    env = {**os.environ, "MISE_TRUSTED_CONFIG_PATHS": f"{spec.work}:{os.environ.get('MISE_TRUSTED_CONFIG_PATHS', '')}".rstrip(":")}
    if bd:
        env.pop("BEADS_DIR", None)
    return env


def tl_argv(spec: Spec, paths: Paths, *args: str) -> list[str]:
    return [str(spec.engine / ".venv/bin/python"), "-I", "-m", "taskloop", "--config", str(paths.config), *args]


class Builder:
    def __init__(self, spec: Spec, proc: Proc) -> None:
        self.spec, self.proc = spec, proc

    def step(self, argv: Sequence[str], *, cwd: Path | None = None, bd: bool = False) -> Captured:
        done = self.proc(argv, cwd=cwd, env=tool_env(self.spec, bd=bd), timeout=SETUP_SECONDS)
        if done.exit:
            raise SetupFailed(f"{' '.join(argv[:5])} exit={done.exit}: {done.err.decode(errors='replace')[-400:]}")
        return done

    def shared(self) -> None:
        """Once per experiment: the empty external tracker for the checks. Idempotent."""
        beads = empty_tracker(self.spec)
        if beads.exists():
            return
        beads.parent.mkdir(parents=True, exist_ok=True)
        self.step(["git", "init", "-q"], cwd=beads.parent)
        self.step(["bd", "init", "--prefix", "empty", "--non-interactive", "--quiet"], cwd=beads.parent, bd=True)

    def arm(self, run: Run) -> str:
        """Build the run's folder from nothing (an earlier folder of the same name is a refusal, never reused) and return
        the arm's base: the frozen base plus the one neutral commit."""
        spec, paths = self.spec, Paths(self.spec, run)
        if len(str(paths.slot).encode()) > SLOT_PATH_LIMIT:
            raise SetupFailed(
                f"Slot path is {len(str(paths.slot).encode())} bytes, over {SLOT_PATH_LIMIT}: use a shorter work folder or repo_name"
            )
        if paths.root.exists():
            raise SetupFailed(f"{paths.root} already exists: remove it or change the seed or name")
        for folder in (paths.slot.parent, paths.tracker, paths.db.parent):
            folder.mkdir(parents=True)
        paths.config.write_text(config_text(spec, run, paths))
        self.step(["git", "clone", "-q", "--bare", str(spec.source), str(paths.origin)])
        self.step(["git", "-C", str(paths.origin), "update-ref", "refs/heads/main", spec.base])
        self.step(["git", "-C", str(paths.origin), "symbolic-ref", "HEAD", "refs/heads/main"])
        self.step(["git", "clone", "-q", str(paths.origin), str(paths.repo)])
        arm_base = self.neutral_commit(paths)
        self.step(["git", "-C", str(paths.repo), "worktree", "add", "-q", "--detach", str(paths.slot)])
        self.tracker(run, paths)
        self.step(
            tl_argv(
                spec, paths, "slot", "adopt", str(paths.repo), "--db", str(paths.db), "--slots-root", str(paths.slots), "--slot-count", "1"
            ),
            cwd=spec.engine,
        )
        return arm_base

    def neutral_commit(self, paths: Paths) -> str:
        profile = paths.repo / ".task-loop.json"
        wrapped = neutral_profile(json.loads(profile.read_text()), empty_tracker(self.spec))
        profile.write_text(json.dumps(wrapped, indent=2) + "\n")
        git = ["git", "-C", str(paths.repo), *IDENTITY]
        self.step([*git, "commit", "-q", "-am", "experiment: land manual, checks see an empty external tracker"])
        self.step([*git, "push", "-q", "origin", "HEAD:main"])
        return self.step(["git", "-C", str(paths.repo), "rev-parse", "HEAD"]).out.decode().strip()

    def tracker(self, run: Run, paths: Paths) -> None:
        task = next(each for each in self.spec.tasks if each.id == run.task)
        self.step(["git", "init", "-q"], cwd=paths.tracker)
        self.step(["bd", "init", "--prefix", task.id.split("-")[0], "--non-interactive", "--quiet"], cwd=paths.tracker, bd=True)
        self.step(
            [
                "bd",
                "create",
                "--id",
                task.id,
                "--title",
                task.title,
                "--type",
                "task",
                "--priority",
                "2",
                "--labels",
                self.spec.label,
                "--description",
                task.text_file.read_text(),
            ],
            cwd=paths.tracker,
            bd=True,
        )
