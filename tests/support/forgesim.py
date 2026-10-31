"""A forge and its remote as a Spawner: `gh pr ...`, `git push`, `git ls-remote` and `git fetch` answered from tables, so a stack
delivery's logic runs with no process. `fail` maps the start of a command's text to the exit code it fails with."""
import json
from collections.abc import Mapping

from taskloop.contracts.argv import text_of
from taskloop.contracts.ports import Ran


class ForgeSim:
    def __init__(self, delete_on_merge: bool = False) -> None:
        self.remote: dict[str, str] = {}  # branch -> oid on origin
        self.prs: dict[int, dict] = {}
        self.fail: dict[str, int] = {}
        self.say: dict[str, str] = {}  # the start of a command's text -> what it prints instead of its answer
        self.missing = False  # no gh or git binary at all
        self.calls: list[str] = []
        self.delete_on_merge = delete_on_merge
        self.main = 0

    def pr(self, number: int, branch: str, oid: str, state: str = "OPEN", base: str = "main") -> None:
        self.prs[number] = {"number": number, "state": state, "headRefName": branch, "headRefOid": oid, "baseRefName": base,
                            "mergeCommit": None, "url": f"https://x/o/r/pull/{number}", "title": branch}
        self.remote.setdefault(branch, oid)

    def ran(self, prefix: str) -> list[str]:
        return [c for c in self.calls if c.startswith(prefix)]

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
            extra: Mapping[str, str] | None = None, timeout_s: float | None = None, capture: bool = True) -> Ran:
        text = text_of(argv)
        self.calls.append(text)
        if self.missing:
            raise FileNotFoundError(argv[0])
        for start, out in self.say.items():
            if text.startswith(start):
                return Ran(exit=0, out=out)
        for start, code in self.fail.items():
            if text.startswith(start):
                return Ran(exit=code, err=f"boom: {start}")
        return self.answer(argv)

    def find(self, ref: str) -> dict | None:
        return self.prs.get(int(ref.rstrip("/").rpartition("/")[2]))

    def answer(self, argv: list[str]) -> Ran:
        head, sub = argv[:3], argv[3:]
        if head[0] == "git":
            return self.git(argv)
        if head[2] == "list":
            branch = sub[sub.index("--head") + 1]
            return Ran(exit=0, out=json.dumps([p for p in self.prs.values() if p["headRefName"] == branch]))
        if head[2] == "view":
            pr = self.find(sub[0])
            return Ran(exit=0, out=json.dumps(pr)) if pr else Ran(exit=1, err="no such pr")
        if head[2] == "create":
            n = max(self.prs, default=0) + 1
            branch = sub[sub.index("--head") + 1]
            self.pr(n, branch, self.remote[branch])
            return Ran(exit=0, out=f"https://x/o/r/pull/{n}\n")
        if head[2] == "edit":
            self.prs[int(sub[0])]["baseRefName"] = sub[sub.index("--base") + 1]
        elif head[2] == "close":
            self.prs[int(sub[0])]["state"] = "CLOSED"
        elif head[2] == "merge":
            return self.merge(self.prs[int(sub[0])], sub[sub.index("--match-head-commit") + 1])
        return Ran(exit=0)

    def merge(self, pr: dict, oid: str) -> Ran:
        if pr["headRefOid"] != oid or self.remote.get(pr["headRefName"]) != oid:
            return Ran(exit=1, err="head branch was modified")
        self.main += 1
        pr["state"], pr["mergeCommit"] = "MERGED", {"oid": f"merge{pr['number']}{'0' * 30}"}
        if self.delete_on_merge:
            self.remote.pop(pr["headRefName"], None)
        return Ran(exit=0)

    def git(self, argv: list[str]) -> Ran:
        if argv[1] == "push":
            oid, _, ref = argv[-1].partition(":")
            self.remote[ref.removeprefix("refs/heads/")] = oid
            for p in self.prs.values():
                if p["state"] == "OPEN" and p["headRefName"] == ref.removeprefix("refs/heads/"):
                    p["headRefOid"] = oid
        if argv[1] == "ls-remote":
            branch = argv[-1].removeprefix("refs/heads/")
            return Ran(exit=0, out=f"{self.remote[branch]}\t{argv[-1]}\n" if branch in self.remote else "")
        return Ran(exit=0)
