"""The guard rails of main (docs/design/merge-queue.md 8.1): what `tl doctor` reads from GitHub and from the machine's git hooks, each
drift a FAIL line, and the exact `gh api` calls an owner runs to set them. Reads only: no code here or anywhere calls a gh api write; a
read that fails (a token scope, a gh that is not there) is a FAIL, never a pass."""
import json
from collections.abc import Callable, Iterable
from pathlib import Path

from taskloop.contracts.procport import Ran

Read = Callable[[str], Ran]  # `gh api PATH`
RULES = frozenset({"deletion", "non_fast_forward"})
MAIN_REFS = frozenset({"refs/heads/main", "~DEFAULT_BRANCH"})


def fetch(read: Read, path: str) -> tuple[object, str]:
    """(the JSON gh printed, '') or (None, why it could not be read)."""
    try:
        ran = read(path)
    except OSError as err:
        return None, f"cannot read {path}: {err}"
    if ran.exit:
        return None, f"cannot read {path} (token scope?): {(ran.err or ran.out).strip()[:120]}"
    try:
        return json.loads(ran.out), ""
    except ValueError:
        return None, f"cannot read {path}: gh printed no JSON"


def obj(x: object) -> dict[str, object]:
    return {str(k): v for k, v in x.items()} if isinstance(x, dict) else {}


def seq(x: object) -> list[object]:
    return list(x) if isinstance(x, list) else []


def covers_main(ruleset: dict[str, object]) -> bool:
    include = {str(i) for i in seq(obj(obj(ruleset.get("conditions")).get("ref_name")).get("include"))}
    return ruleset.get("target") == "branch" and ruleset.get("enforcement") == "active" and bool(MAIN_REFS & include)


def ruleset_findings(read: Read, slug: str, check_names: Iterable[str]) -> list[str]:
    """FAIL lines: the no-force-push, no-deletion ruleset missing or loosened; a required-PR or required-check rule that is not the
    profile's check set; strict up-to-date on."""
    listed, why = fetch(read, f"repos/{slug}/rulesets")
    if not isinstance(listed, list):
        return [why or f"cannot read repos/{slug}/rulesets"]
    full: list[dict[str, object]] = []
    for row in listed:
        one, why = fetch(read, f"repos/{slug}/rulesets/{obj(row).get('id')}")
        if not isinstance(one, dict):
            return [why or "a ruleset is not a JSON object"]
        full.append(obj(one))
    out: list[str] = []
    mine = [r for r in full if covers_main(r)]
    if not any({str(obj(x).get("type")) for x in seq(r.get("rules"))} >= RULES and not r.get("bypass_actors") for r in mine):
        out.append("main has no active ruleset with deletion and non_fast_forward and no bypass actors "
                   "(`tl doctor --print-guard-rails` prints the call that adds it)")
    needed = set(check_names)
    for r in mine:
        for rule in map(obj, seq(r.get("rules"))):
            params = obj(rule.get("parameters"))
            if rule.get("type") == "pull_request":
                out.append(f"ruleset {r.get('id')} requires a pull request on main: land_mode push and release push to main directly")
            if rule.get("type") == "required_status_checks":
                have = {str(obj(c).get("context")) for c in seq(params.get("required_status_checks"))}
                if have != needed:
                    out.append(f"ruleset {r.get('id')} requires checks {sorted(have)}; the profile's check set is {sorted(needed)}")
                if params.get("strict_required_status_checks_policy"):
                    out.append(f"ruleset {r.get('id')} requires branches to be up to date: the queue's merges are refused then")
    return out + protection_findings(read, slug, needed)


def protection_findings(read: Read, slug: str, needed: set[str]) -> list[str]:
    """The classic branch protection of main: none (404) is fine, an unreadable one is not."""
    ran = read(f"repos/{slug}/branches/main/protection")
    if ran.exit:
        text = ran.err + ran.out
        return [] if "404" in text and "not protected" in text.lower() else [
            f"cannot read repos/{slug}/branches/main/protection (token scope?): {text.strip()[:120]}"]
    try:
        loaded = json.loads(ran.out)
    except ValueError:
        loaded = None
    if not isinstance(loaded, dict):
        return [f"cannot read repos/{slug}/branches/main/protection: gh printed no JSON object"]
    data = obj(loaded)
    out: list[str] = []
    if "required_pull_request_reviews" in data:
        out.append("branch protection of main requires pull request reviews: land_mode push and release push to main directly")
    checks = obj(data.get("required_status_checks"))
    if checks:
        have = {str(c) for c in seq(checks.get("contexts"))}
        if have != needed:
            out.append(f"branch protection requires checks {sorted(have)}; the profile's check set is {sorted(needed)}")
        if checks.get("strict"):
            out.append("branch protection requires branches to be up to date: the queue's merges are refused then")
    return out


def hook_findings(hooks_dir: Path, expected: str, worktrees: Iterable[tuple[str, str]]) -> list[str]:
    """FAIL lines: tl's pre-push dispatcher missing or not the current text, and a worktree whose own core.hooksPath bypasses it.
    `worktrees` is (path, its core.hooksPath setting); tl's children get hooks_dir from the engine, so an empty setting is fine."""
    out: list[str] = []
    hook = hooks_dir / "pre-push"
    try:
        if hook.read_text(encoding="utf-8") != expected:
            out.append(f"{hook} is not the current pre-push judge: `tl setup --apply`")
    except OSError:
        out.append(f"{hook} is missing: pushes are not judged; `tl setup --apply`")
    out += [f"worktree {path} sets core.hooksPath to {setting}: tl's pre-push judge does not run there"
            for path, setting in worktrees if setting and Path(setting) != hooks_dir]
    return out


def print_calls(slug: str) -> str:
    """The calls that set the guard rails; the owner runs them, nothing here does."""
    ruleset: dict[str, object] = {"name": "main: no force-push, no deletion", "target": "branch", "enforcement": "active",
               "bypass_actors": [],
               "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
               "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}
    full: dict[str, object] = {**ruleset, "name": "main: queue-only updates", "rules": [{"type": "update"}],
            "bypass_actors": [{"actor_id": "<id of the queue's app or role>", "actor_type": "<Integration|RepositoryRole>",
                               "bypass_mode": "always"}]}
    return "\n".join([
        "# the ruleset the doctor requires (no force-push, no deletion on main; no required PR, no required checks):",
        f"gh api -X POST repos/{slug}/rulesets --input - <<'JSON'", json.dumps(ruleset, indent=2), "JSON",
        "# rollback:", f"gh api -X DELETE repos/{slug}/rulesets/<id>",
        "# optional, later: only the queue's identity may update main (add after land push and release go through the queue):",
        f"gh api -X POST repos/{slug}/rulesets --input - <<'JSON'", json.dumps(full, indent=2), "JSON", ""])
