"""`tl setup --apply`: make the safe machine fixes and, when the repo has no profile, put the owner's answers into a pull request.
The profile goes in as a PR, never onto the base branch: the loop reads the profile from the base commit, so it only counts once merged."""
import base64
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from tlkernel.config import HostResources
from tlkernel.delegateport import Route
from tlkernel.env import Env
from tlkernel.procport import Ran

from taskloop.app.doctor import install, setup

BRANCH = "tl-setup-profile"
REF = "repos/{owner}/{repo}/git/ref/heads/"  # gh fills {owner} and {repo} from the repo it runs in


class HostStore(Protocol):
    def get(self) -> HostResources | None: ...

    def write(self, rec: HostResources, /) -> None: ...


class Runs(Protocol):
    def run(self, argv: list[str], *, cwd: str | None = None) -> Ran: ...


def machine_fixes(plugin_root: Path, env: Env, route: Route) -> list[str]:
    """The idempotent per-user fixes (what SessionStart makes too); -> the ids of those that were to do."""
    todo = [f.id for f in setup.machine(plugin_root, env, route).fixes]
    install.ensure_machine(plugin_root, env)
    return todo


def profile_of(answers: Mapping[str, str]) -> dict[str, object]:
    """The .task-loop.json the answers describe: a Unity lease, the repo gate."""
    engine: dict[str, object] = {}
    unity = answers.get("unity-lease") == "yes"
    if unity:
        engine["resources"] = {"unity": {"limit": 1}}
    if answers.get("gate") == "yes":
        engine["checks"] = [{"id": "gate", "argv": ["just", "check"], **({"needs": ["unity"]} if unity else {})}]
    return {"engine": engine}


def host_fix(answers: Mapping[str, str], store: HostStore) -> list[str]:
    """host.json from the unity-lease answer: a host that answered yes has the unity resource. An existing file is the person's: kept."""
    if answers.get("unity-lease") != "yes":
        return []
    if store.get() is not None:
        return []
    store.write(HostResources(resources=["unity"]))
    return ["wrote host.json: this machine has unity"]


def open_pr(repo: Path, profile: dict[str, object], sh: Runs) -> tuple[bool, str]:
    """The profile as a PR through `gh` alone (no local branch, no push): the base branch's tip, a new branch at it, the file committed
    on that branch over the API, a PR opened. (ok, the PR url or why not)."""
    def gh(*argv: str) -> Ran:
        return sh.run(["gh", *argv], cwd=str(repo))

    def failed(what: str, ran: Ran) -> tuple[bool, str]:
        return False, f"gh {what} failed: {(ran.err or ran.out).strip()[:200]}"

    base = gh("repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name")
    if base.exit != 0:
        return failed("repo view", base)
    name = base.out.strip()
    tip = gh("api", REF + name, "--jq", ".object.sha")
    if tip.exit != 0:
        return failed("api ref", tip)
    made = gh("api", "repos/{owner}/{repo}/git/refs", "-f", f"ref=refs/heads/{BRANCH}", "-f", f"sha={tip.out.strip()}")
    if made.exit != 0:
        return failed("api refs", made)
    content = base64.b64encode((json.dumps(profile, indent=2) + "\n").encode()).decode()
    put = gh("api", "-X", "PUT", "repos/{owner}/{repo}/contents/.task-loop.json", "-f", "message=task-loop: the repo profile",
             "-f", f"content={content}", "-f", f"branch={BRANCH}")
    if put.exit != 0:
        return failed("api contents", put)
    pr = gh("pr", "create", "--base", name, "--head", BRANCH, "--title", "task-loop: the repo profile",
            "--body", "Written by `tl setup --apply` from the owner's answers. The loop reads the base commit: it counts once merged.")
    return (True, pr.out.strip()) if pr.exit == 0 else failed("pr create", pr)


def apply(
    plugin_root: Path, env: Env, repo: Path | None, answers: Mapping[str, str], sh: Runs, facts: setup.ProfileFacts,
    route: Route, host: HostStore,
) -> tuple[int, list[str]]:
    """-> (exit code, report lines). A question left unanswered opens no PR."""
    lines = [f"fixed {fix}" for fix in machine_fixes(plugin_root, env, route)] or ["machine: nothing to fix"]
    if repo is None:
        return 0, lines
    asks = setup.repo_part(repo, facts).questions
    if not asks:
        return 0, lines
    missing = [q.id for q in asks if q.id not in answers]
    if missing:
        return 1, [*lines, "profile: no answer for " + ", ".join(missing) + " (--answers FILE or --yes)"]
    lines += host_fix(answers, host)
    ok, detail = open_pr(repo, profile_of(answers), sh)
    return (0, [*lines, f"profile: PR {detail}"]) if ok else (1, [*lines, f"profile: {detail}"])
