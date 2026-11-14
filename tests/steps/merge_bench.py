"""The merge feature's semantic Git and durable SQLite bench, without a scheduler or real process."""

import sqlite3
from dataclasses import dataclass

from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import Recorded, Tree
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree

from taskloop.agents.settings import AgentSetting
from taskloop.merge.models import Answer, Disposition, Execution, Waiting, Work
from taskloop.merge.start import Merge
from taskloop.merge.store import MergeStore


class MergeRepo(FakeRepo):
    """The shelf fake supports `^` but omits numbered-parent revisions; supply that semantic read for merge tests."""

    def tree(self, rev: str) -> Tree | None:
        base, _, number = rev.rpartition("^")
        if base and number.isdigit():
            commit = super().tree(base)
            if commit is None:
                return None
            parents = self._state.store.commits[commit.sha].parents
            index = int(number) - 1
            return super().tree(parents[index]) if 0 <= index < len(parents) else None
        return super().tree(rev)


def head(slot: FakeWorktree) -> str:
    found = next(info.head for info in slot.repo.worktrees() if info.path == slot.path)
    assert found is not None
    return found


@dataclass
class Bench:
    repo: FakeRepo
    remote: FakeRemote
    slot: FakeWorktree
    files: FakeSlotFiles
    views: PinnedViews
    store: MergeStore
    work: Work
    calls: list[str]

    def setup(self, work: Work) -> Waiting | None:
        assert head(self.slot) == work.target and self.slot.branch() is None and not self.slot.merging()
        self.calls.append("setup")
        return None

    def resolve(self, work: Work) -> Work:
        self.calls.append("resolve")
        self.slot.write_file("README", "the task\ncurrent main\n")
        answer = Answer(disposition=Disposition.RESOLVED, paths=("README",), explanation="Retain both changes.")
        execution = Execution(number=len(work.executions) + 1, ended=True, answer=answer)
        return self.store.put(work, work.model_copy(update={"executions": (*work.executions, execution)}))

    def operation(self) -> Merge:
        return Merge(self.store, self.views, self.views, self.files, lambda: 10, self.setup, self.resolve)


def bench(con: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
          files: FakeSlotFiles, views: PinnedViews, conflict: bool = False) -> Bench:
    base = head(slot)
    task = repo.add_worktree(slot.path.parent / "author", "HEAD")
    task.checkout_new("task/tl-1")
    task.write_file("docs/design/tl-1/plan.md", "Retain the plan.\n")
    if conflict:
        task.write_file("README", "the task\n")
    recorded = task.record("Plan\n\nTask-Loop-Attempt: plan", paths="all")
    assert isinstance(recorded, Recorded)
    source = str(recorded.sha)
    task.park(source)
    repo.drop_worktree(task.path)
    remote.advance("main", {"README": "current main\n", "other": "another landed task\n"})
    assert repo.fetch().ok
    slot.take_branch("task/tl-1", source, mode="resume")
    work = Work(attempt_id="attempt", dispatch_token="dispatch", generation=1, task_id="tl-1", repo_id=repo.identity().key,
                root=repo.path, slot=slot.path, gitdir=repo.identity().common_dir / "worktrees" / slot.path.name,
                base=base, source=source, branch="task/tl-1", deadline=100, setting=AgentSetting(),
                input_path="input.txt", input_digest="digest")
    store = MergeStore(lambda: con)
    return Bench(repo, remote, slot, files, views, store, store.start(work), [])
