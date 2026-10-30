"""Every file location, once. Nothing else in the package names a file or a folder of ours."""
from pathlib import Path
from typing import Final, final

from taskloop.contracts import env as penv
from taskloop.contracts.ids import BeadId, RunId


def default_root() -> Path:
    """~/.config/task-loop, or $XDG_CONFIG_HOME/task-loop. Not created here."""
    base = penv.ambient("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "task-loop"


@final
class ConfigDir:
    """The per-user state folder."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()

    def engine_log(self, run: RunId | str) -> Path:
        return self.root / "engine" / (f"{run}.jsonl")

    def live_dir(self, run: RunId | str) -> Path:
        return self.root / "engine" / (f"{run}.live")

    def events(self) -> Path:
        return self.root / "events.jsonl"

    def traces(self) -> Path:
        return self.root / "traces.jsonl"

    def ask(self, bead: BeadId | str) -> Path:
        return self.root / "asks" / (f"{bead}.json")

    def asks_dir(self) -> Path:
        return self.root / "asks"

    def ask_beads(self) -> list[str]:
        """The beads that have an ask file, sorted."""
        try:
            return sorted(p.stem for p in self.asks_dir().glob("*.json"))
        except OSError:
            return []

    def ask_marker(self, sweep: str) -> Path:
        """When a throttled sweep of the asks last ran (the file's mtime); not an ask, so the store never lists it."""
        return self.root / "asks" / ("." + sweep)

    def ask_ledger(self) -> Path:
        """The append-only ledger of every ask transition; never swept."""
        return self.root / "ask-ledger.jsonl"

    def adr_dir(self, repo_key: str) -> Path:
        return self.root / "decisions" / repo_key

    def adr(self, repo_key: str, adr: str) -> Path:
        return self.adr_dir(repo_key) / (f"{adr}.json")

    def adr_ids(self, repo_key: str) -> list[str]:
        """The ids of a repo's decisions (ADR-1, ADR-2, ...), by number."""
        try:
            found = [p.stem for p in self.adr_dir(repo_key).glob("*.json")]
        except OSError:
            return []
        return sorted((k for k in found if k[:4] == "ADR-" and k[4:].isdigit()), key=lambda k: int(k[4:]))

    def adr_uses(self, repo_key: str) -> Path:
        return self.adr_dir(repo_key) / "uses.jsonl"

    def landed(self, bead: BeadId | str) -> Path:
        """The record that a bead's work reached its base (contracts/landed.py)."""
        return self.root / "landed" / (f"{bead}.json")

    def checkpoint(self, bead: BeadId | str) -> Path:
        return self.root / "checkpoints" / (f"{bead}.json")

    def run_dir(self, run: RunId | str) -> Path:
        return self.root / "runs" / str(run)

    def run_request(self, run: RunId | str) -> Path:
        """The owner's requests to the live run (park, stop, notes): contracts/requests.py; the run takes it at a step boundary."""
        return self.run_dir(run) / "owner-request.json"

    def run_request_lock(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "owner-request.lock"

    def check_run(self, run: RunId | str, rnd: int | None = None) -> Path:
        """The CheckRun of a round of the run; no round: the latest."""
        return self.run_dir(run) / ("engine-checks.json" if rnd is None else f"engine-checks.r{int(rnd)}.json")

    def check_logs(self, run: RunId | str) -> Path:
        return self.run_dir(run) / "checks"

    def artifacts(self, bead: BeadId | str) -> Path:
        """The plain files a bead's runs left (screenshots, PDFs): one flat directory per bead, outside every worktree."""
        return self.root / "artifacts" / str(bead)

    def check_cache(self, bead: BeadId | str) -> Path:
        return self.root / "check-cache" / (f"{bead}.json")

    def check_durations(self, repo_key: str) -> Path:
        return self.root / "check-durations" / (f"{repo_key}.json")

    def loop_state(self, repo_key: str) -> Path:
        return self.root / "loop" / (f"{repo_key}.json")

    def loop_command(self, repo_key: str) -> Path:
        return self.root / "loop" / (f"{repo_key}.command.json")

    def loop_log(self, repo_key: str) -> Path:
        return self.root / "loop" / (f"{repo_key}.jsonl")

    def loop_runs(self, repo_key: str) -> Path:
        """The loop's own folder of the repo: run logs, outcome files, loop-<pid>.log, exits.jsonl, died-<pid>.json."""
        return self.root / "loop" / repo_key

    def loop_rest(self, repo_key: str) -> Path:
        return self.root / "loop" / (f"{repo_key}-rest.json")

    def ticket(self, repo_key: str, seq: int) -> Path:
        return self.root / "slots" / repo_key / (f"{int(seq):06d}.json")

    def ticket_counter(self, repo_key: str) -> Path:
        return self.root / "slots" / repo_key / "seq"

    def slot_state(self, repo_key: str, slot: str) -> Path:
        """What one slot of one repo keeps for its commands (temp, dotnet and NuGet scratch): outside the worktree, kept across reuse."""
        return self.root / "slot-state" / repo_key / slot

    def slot_setup_mark(self, key: str) -> Path:
        return self.root / "slots" / (f"{key}.setup")

    def lock_record(self, what: str, ident: str) -> Path:
        return self.root / "locks" / (f"{what}-{ident}.lock")

    def snapshot(self, repo_key: str, name: str) -> Path:
        return self.root / "snapshots" / (f"{repo_key}.{name}.json")

    def session(self, session_id: str) -> Path:
        return self.root / "sessions" / (f"{session_id}.json")

    def repos(self) -> Path:
        return self.root / "repos.json"

    def shared(self, repo_key: str) -> Path:
        return self.root / "shared" / (f"{repo_key}.json")

    def pin(self) -> Path:
        return self.root / "pinned.json"

    def bad_versions(self) -> Path:
        return self.root / "bad-versions.json"

    def release_result(self) -> Path:
        return self.root / "releases" / "last.json"

    def suite_logs(self) -> list[Path]:
        """The saved full output of every red release suite (releases/suite-*.log); nothing sweeps them but `tl prune`."""
        return sorted((self.root / "releases").glob("suite-*.log"))

    def reflect_view(self) -> Path:
        return self.root / "reflect-view.json"

    def handoff(self, repo_key: str) -> Path:
        return self.root / "handoff" / (f"{repo_key}.md")

    def dash_state(self) -> Path:
        return self.root / "dash.json"

    def usage_history(self) -> Path:
        return self.root / "usage-history.jsonl"


PLAN_FILE: Final = "plan.json"  # the run directory's copy of the plan the dashboard reads
TASK_EXCLUDE: Final = ".task/"  # the line a repo's info/exclude carries so the scratch folder is never committed


@final
class RepoDirs:
    """The scratch folder a worktree carries (.task/, never committed)."""

    def __init__(self, worktree: Path | str) -> None:
        self.worktree = Path(worktree)
        self.task = self.worktree / ".task"

    def engine_lock(self) -> Path:
        return self.task / "engine.lock"

    def artifacts(self, bead: str) -> Path:
        """Where a run drops screenshots, PDFs: `StepArtifacts` copies the files from here when a step ends."""
        return self.task / bead / "artifacts"

    def check_log(self, name: str) -> Path:
        return self.task / "checks" / name
