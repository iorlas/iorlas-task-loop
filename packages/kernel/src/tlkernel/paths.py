"""Shared state paths used by the kernel and multiple application stages."""
from pathlib import Path
from typing import Final, final

from tlkernel.env import Env
from tlkernel.ids import RunId


def default_root(env: Env) -> Path:
    """~/.config/task-loop, or $XDG_CONFIG_HOME/task-loop, of `env`. Not created here."""
    return Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "task-loop"


@final
class ConfigDir:
    """The per-user state folder."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def factory_db(self) -> Path:
        """The host's shared factory journal and dashboard read model."""
        return self.root / "factory.db"

    def runs_dir(self) -> Path:
        return self.root / "runs"

    def hooks_dir(self) -> Path:
        """githooks/: the git hooks the engine writes at start; every subprocess tl starts gets it as core.hooksPath (adapters/childenv)."""
        return self.root / "githooks"

    def repos_dir(self) -> Path:
        """repos/<repo-key>/: what is scoped to one repo (loop, slots, slot-state, decisions, durations)."""
        return self.root / "repos"

    def repo_dir(self, repo_key: str) -> Path:
        return self.repos_dir() / repo_key

    def engine_log(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "engine.jsonl"

    def engine_stderr(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "stderr.log"

    def live_dir(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "live"

    def events(self) -> Path:
        return self.root / "events.jsonl"

    def traces(self) -> Path:
        return self.root / "traces.jsonl"

    def profile_changes(self) -> Path:
        """The owner's audit of profile changes delivered by land-stack."""
        return self.root / "profile-changes.jsonl"

    def adr_dir(self, repo_key: str) -> Path:
        return self.repo_dir(repo_key) / "decisions"

    def adr_uses(self, repo_key: str) -> Path:
        return self.adr_dir(repo_key) / "uses.jsonl"

    def run_dir(self, run: RunId | str) -> Path:
        return self.runs_dir() / str(run)

    def run_request(self, run: RunId | str) -> Path:
        """The owner's requests to the live run (park, stop, notes): contracts/requests.py; the run takes it at a step boundary."""
        return self.run_dir(run) / "owner-request.json"

    def run_request_lock(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "owner-request.lock"

    def check_run(self, run: RunId | str, rnd: int | None = None) -> Path:
        """The CheckRun of a round of the run; no round: the latest."""
        return self.run_dir(run) / ("engine-checks.json" if rnd is None else f"engine-checks.r{rnd}.json")

    def artifact_store(self) -> Path:
        """The artifact store's root: <root>/<repo>/<bead>/<run>/<stage>-<attempt>/<name> (contracts/artifact.py)."""
        return self.root / "artifacts"

    def lock_file(self, name: str) -> Path:
        """locks/<name>: a lock of the host that is not keyed to one worktree (release, reflect, slot take)."""
        return self.root / "locks" / name

    def loop_log(self, repo_key: str) -> Path:
        return self.loop_runs(repo_key) / "log.jsonl"

    def loop_runs(self, repo_key: str) -> Path:
        """The loop's own folder of the repo: run logs, outcome files, loop-<pid>.log, exits.jsonl, died-<pid>.json."""
        return self.repo_dir(repo_key) / "loop"

    def host(self) -> Path:
        """host.json: what this machine has (the resources checks may need). A person writes it; absent: the host has every resource."""
        return self.root / "host.json"

    def lock_record(self, what: str, ident: str) -> Path:
        return self.lock_file(f"{what}-{ident}.lock")

    def leases(self) -> Path:
        """The lease table (any_lease): `<name>.limit` and `<name>-<n>.lock` for each engine.resources entry, shared with manual
        runs (`python3 -m any_lease run --root <this> unity N label -- cmd`)."""
        return self.root / "leases"

    def repos(self) -> Path:
        return self.root / "repos.json"

    def shared(self, repo_key: str) -> Path:
        return self.root / "shared" / (f"{repo_key}.json")

    def pin(self) -> Path:
        return self.root / "pinned.json"

    def handoff(self, repo_key: str) -> Path:
        return self.root / "handoff" / (f"{repo_key}.md")

    def usage_history(self) -> Path:
        return self.root / "usage-history.jsonl"


PLAN_FILE: Final = "plan.json"  # the run directory's copy of the plan the dashboard reads


@final
class RunFiles:
    """The state files inside one run directory (runs/<run>/)."""

    def __init__(self, run_dir: Path | str) -> None:
        self.dir = Path(run_dir)

    def attempts(self) -> Path:
        """attempts/: one folder per run attempt (a process that took the run up; the factory.db attempt row's n)."""
        return self.dir / "attempts"

    def attempt(self, n: int) -> Path:
        """attempts/<run>-attempt-<n>/: what run attempt n wrote."""
        return self.attempts() / f"{self.dir.name}-attempt-{n}"

    def artifacts(self, n: int) -> Path:
        """The folders of the checks run in run attempt n, one per step, each holding attempt-S/ (S: the step's own try)."""
        return self.attempt(n) / "artifacts"


TASK_EXCLUDE: Final = ".task/"  # the line a repo's info/exclude carries so the scratch folder is never committed
