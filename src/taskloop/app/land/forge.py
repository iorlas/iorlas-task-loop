"""The forge and the remote as a stack delivery asks them: `gh` for the PRs, `git push` and `git ls-remote` for the branches. Every call is
a row (Cmds). What a PR body or a title says is data: nothing of it is ever run, and the text this writes is its own."""
import json
from collections.abc import Mapping
from types import MappingProxyType

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.contracts.forge import MERGED, OPEN, Pr, gh_pr
from taskloop.contracts.ports import Git

FIELDS = "number,state,headRefName,headRefOid,baseRefName,mergeCommit,url,title"
MERGE_FLAG: Mapping[str, str] = MappingProxyType({"squash": "--squash", "merge": "--merge", "rebase": "--rebase"})


def loads(text: str, what: str, many: bool = False) -> list[Pr]:
    """The PRs gh printed (one object, or a list with `many`); anything else stops the delivery."""
    try:
        data = json.loads(text)
        return [gh_pr(d) for d in (data if many else [data])]
    except ValueError:  # a bad JSON text, or a ValidationError (a ValueError) from the record
        raise Stop(1, f"{what}: gh answered something that is not a PR: {text.strip()[:200]!r}") from None


class Forge:
    def __init__(self, cmds: Cmds, git: Git, repo: str, base: str, method: str = "squash", remote: str = "origin") -> None:
        self.cmds, self.git, self.repo, self.base, self.method, self.remote = cmds, git, repo, base, method, remote

    def view(self, ref: str | int) -> Pr:
        out = self.cmds.must(["gh", "pr", "view", str(ref), "--json", FIELDS]).out
        return loads(out, f"gh pr view {ref}")[0]

    def find(self, branch: str, oid: str) -> Pr | None:
        """The PR of this branch head: an open one, else one already merged at this very head (a rerun), else None."""
        out = self.cmds.must(["gh", "pr", "list", "--head", branch, "--state", "all", "--json", FIELDS, "--limit", "20"]).out
        prs = loads(out, f"gh pr list --head {branch}", many=True)
        return next((p for p in prs if p.state == OPEN), None) or next((p for p in prs if p.state == MERGED and p.head_oid == oid), None)

    def create(self, branch: str, title: str, body: str) -> Pr:
        out = self.cmds.must(["gh", "pr", "create", "--head", branch, "--base", self.base, "--title", title, "--body", body]).out
        url = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip().startswith("http")), "")
        if not url:
            raise Stop(1, f"gh pr create for {branch} printed no PR url: {out.strip()[-200:]!r}")
        return self.view(url)

    def retarget(self, pr: Pr) -> None:
        self.cmds.must(["gh", "pr", "edit", str(pr.number), "--base", self.base])

    def merge(self, pr: Pr, oid: str) -> None:
        """Merge only the head we saw: the forge refuses when the branch moved. The branch is left to the forge (no --delete-branch)."""
        self.cmds.must(["gh", "pr", "merge", str(pr.number), MERGE_FLAG[self.method], "--match-head-commit", oid])

    def close(self, number: int, comment: str) -> None:
        self.cmds.must(["gh", "pr", "close", str(number), "--comment", comment])

    def push(self, branch: str, oid: str) -> None:
        """Push exactly `oid` to the branch (no force; the repo's pre-push hook decides, as for any push) and see it on the remote."""
        spec = f"{oid}:refs/heads/{branch}"
        self.cmds.port(f"git push {self.remote} {spec}", lambda: self.git.push(self.repo, self.remote, spec))
        there = self.remote_oid(branch)
        if there != oid:
            raise Stop(1, f"pushed {branch} at {oid[:12]} but {self.remote} shows {there[:12] or 'no such branch'}")

    def remote_oid(self, branch: str) -> str:
        """The oid the remote shows for the branch, '' when it has none (a branch the forge deleted on merge is gone, not a failure)."""
        ref = f"refs/heads/{branch}"
        refs = self.cmds.port(f"git ls-remote {self.remote} {ref}", lambda: self.git.ls_remote(self.repo, self.remote, ref))
        return next((r.oid for r in refs if r.name == ref), "")

    def fetch(self) -> None:
        self.cmds.port(f"git fetch {self.remote}", lambda: self.git.fetch(self.repo))
