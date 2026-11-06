"""Every file location, once. Nothing else in the package names a file or a folder of ours."""
import hashlib
from pathlib import Path
from typing import Final, final

from taskloop.contracts.env import Env
from taskloop.contracts.ids import BeadId, RunId, loop_key


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

    def land_push(self, stamp: int, branch: str) -> Path:
        return self.root / "land-push" / f"{stamp}-{branch}.log"

    def hooks_dir(self) -> Path:
        """githooks/: the git hooks the engine writes at start; every subprocess tl starts gets it as core.hooksPath (adapters/childenv)."""
        return self.root / "githooks"

    def layout_journal(self) -> Path:
        """What `tl layout migrate` moved, one line per move."""
        return self.root / "layout-migrate.jsonl"

    def dash_pid(self) -> Path:
        return self.root / "dash.pid"

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

    def ask(self, bead: BeadId | str) -> Path:
        """Legacy ask input for the one-time importer only."""
        return self.root / "asks" / (f"{bead}.json")

    def asks_dir(self) -> Path:
        """Legacy ask directory for the one-time importer only."""
        return self.root / "asks"

    def ask_beads(self) -> list[str]:
        """Legacy beads, sorted; used only by the one-time importer."""
        try:
            return sorted(p.stem for p in self.asks_dir().glob("*.json"))
        except OSError:
            return []

    def ask_marker(self, sweep: str) -> Path:
        """When a throttled sweep of the asks last ran (the file's mtime); not an ask, so the store never lists it."""
        return self.root / "asks" / ("." + sweep)

    def ask_ledger(self) -> Path:
        """Legacy ledger input for the one-time importer only."""
        return self.root / "ask-ledger.jsonl"

    def adr_dir(self, repo_key: str) -> Path:
        return self.repo_dir(repo_key) / "decisions"

    def adr(self, repo_key: str, adr: str) -> Path:
        return self.adr_dir(repo_key) / (f"{adr}.json")

    def adr_uses(self, repo_key: str) -> Path:
        return self.adr_dir(repo_key) / "uses.jsonl"

    def checkpoint(self, bead: BeadId | str) -> Path:
        return self.root / "checkpoints" / (f"{bead}.json")

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

    def releases_dir(self) -> Path:
        return self.root / "releases"

    def lock_file(self, name: str) -> Path:
        """locks/<name>: a lock of the host that is not keyed to one worktree (release, reflect, slot take)."""
        return self.root / "locks" / name

    def result(self, repo_key: str, check: str, digest: str) -> Path:
        """Legacy importer only: receipt rollback copy under the hashed check ID; current receipts live in factory.db."""
        return self.root / "results" / repo_key / hashlib.sha1(check.encode("utf-8", "surrogateescape")).hexdigest()[:12] / f"{digest}.json"

    def base_red(self, repo_key: str, digest: str) -> Path:
        """Legacy importer only: base-red rollback copy; current receipts live in factory.db."""
        return self.root / "results" / repo_key / "base-red" / f"{digest}.json"

    def check_durations(self, repo_key: str) -> Path:
        return self.repo_dir(repo_key) / "durations.json"

    def loop_log(self, repo_key: str) -> Path:
        return self.loop_runs(repo_key) / "log.jsonl"

    def loop_runs(self, repo_key: str) -> Path:
        """The loop's own folder of the repo: run logs, outcome files, loop-<pid>.log, exits.jsonl, died-<pid>.json."""
        return self.repo_dir(repo_key) / "loop"

    def slot_state(self, repo_key: str, slot: str) -> Path:
        """What one slot of one repo keeps for its commands (temp, dotnet and NuGet scratch): outside the worktree, kept across reuse."""
        return self.repo_dir(repo_key) / "slot-state" / slot

    def slot_setup_mark(self, key: str) -> Path:
        return self.root / "slots" / (f"{key}.setup")

    def host(self) -> Path:
        """host.json: what this machine has (the resources checks may need). A person writes it; absent: the host has every resource."""
        return self.root / "host.json"

    def engine_lock(self, wt: Path | str) -> Path:
        """The engine lock of a worktree: out of the tree, where no worker can write it (Z15). Keyed like the loop's files."""
        return self.lock_record("engine", loop_key(wt))

    def engine_take(self, wt: Path | str) -> Path:
        """Held (locks.hold_path) while a run checks the engine lock and writes its own: two runs starting at once cannot both win."""
        return self.lock_record("engine-take", loop_key(wt))

    def lock_record(self, what: str, ident: str) -> Path:
        return self.lock_file(f"{what}-{ident}.lock")

    def leases(self) -> Path:
        """The lease table (any_lease): `<name>.limit` and `<name>-<n>.lock` for each engine.resources entry, shared with manual
        runs (`python3 -m any_lease run --root <this> unity N label -- cmd`)."""
        return self.root / "leases"

    def snapshot(self, repo_key: str, name: str) -> Path:
        return self.root / "snapshots" / (f"{repo_key}.{name}.json")

    def repos(self) -> Path:
        return self.root / "repos.json"

    def shared(self, repo_key: str) -> Path:
        return self.root / "shared" / (f"{repo_key}.json")

    def pin(self) -> Path:
        return self.root / "pinned.json"

    def bad_versions(self) -> Path:
        return self.root / "bad-versions.json"

    def release_result(self) -> Path:
        return self.releases_dir() / "last.json"

    def suite_logs(self) -> list[Path]:
        """The saved full output of every red release suite (releases/suite-*.log); nothing sweeps them but `tl prune`."""
        return sorted(self.releases_dir().glob("suite-*.log"))

    def reflect_state(self) -> Path:
        return self.root / "reflect-digest.json"

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

    def pause(self) -> Path:
        return self.dir / "pause.json"

    def push_log(self, stamp: int) -> Path:
        return self.dir / "land-push" / f"{stamp}.log"

    def reexec(self) -> Path:
        return self.dir / "reexec.json"

    def artifacts(self) -> Path:
        """The folders of the run's checks, one per step, each holding attempt-N/ (contracts/artifact.py)."""
        return self.dir / "artifacts"

    def handoff(self) -> Path:
        return self.dir / "handoff.json"

    def prepare_stamp(self) -> Path:
        return self.dir / "prepare.stamp"


TASK_EXCLUDE: Final = ".task/"  # the line a repo's info/exclude carries so the scratch folder is never committed
