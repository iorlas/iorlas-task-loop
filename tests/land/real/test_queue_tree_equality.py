"""MQUEUE premise (merge-queue.md 3.4): the merge-tree chain Q1..Qn has the trees of the PRs squashed one by one onto a moving main."""
import os
import random
import subprocess
from pathlib import Path

import pytest

CASES, CHUNKS = 1000, 10
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0",  # a gc would prune the refless objects
           "GIT_CONFIG_KEY_1": "maintenance.auto", "GIT_CONFIG_VALUE_1": "false"}
Files = dict[str, list[str]]


def git(cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True, text=True, check=False,
                          env={**os.environ, **GIT_ENV})


def out(cwd: Path, *args: str) -> str:
    r = git(cwd, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def base_files() -> Files:
    return {f"f{i}.txt": [f"f{i} line {j}" for j in range(12)] for i in range(5)}


def mutate(rng: random.Random, files: Files, tag: str) -> None:
    """One random edit, add, delete or rename on `files`."""
    op = rng.choice(["edit", "edit", "add", "delete", "rename"])
    names = sorted(files)
    if op == "add" or not names:
        files[f"n_{tag}.txt"] = [f"{tag} new {j}" for j in range(6)]
    elif op == "edit":
        name = rng.choice(names)
        files[name][rng.randrange(len(files[name]))] = f"{tag} edit"
    elif op == "delete":
        del files[rng.choice(names)]
    else:
        name = rng.choice(names)
        files[f"r_{tag}.txt"] = files.pop(name)


def commit_script(branch: str, mark: int, parent: str, files: Files) -> str:
    lines = [f"commit refs/heads/{branch}", f"mark :{mark}", "committer t <t@t> 1 +0000", "data 1", "c",
             *([f"from {parent}"] if parent else []), "deleteall"]
    for name, body in files.items():
        data = "\n".join(body) + "\n"
        lines += [f"M 100644 inline {name}", f"data {len(data)}", data.rstrip("\n")]
    return "\n".join(lines) + "\n\n"


def build(repo: Path, rng: random.Random, n: int) -> list[str]:
    """base on main (maybe one unrelated commit past it), then n PR branches of 1-3 commits: branched from base (stale) or from main."""
    base = base_files()
    script, mark = commit_script("main", 1, "", base), 1
    main_files = dict(base)
    if rng.random() < 0.5:
        mark += 1
        main_files["f4.txt"] = ["main moved"] * 3 + base["f4.txt"]
        script += commit_script("main", mark, ":1", main_files)
    main_mark = mark
    heads: list[str] = []
    for k in range(n):
        start = rng.choice([(1, base), (main_mark, main_files)])
        parent, files = f":{start[0]}", {name: list(body) for name, body in start[1].items()}
        for c in range(rng.randint(1, 3)):
            mark += 1
            mutate(rng, files, f"p{k}c{c}")
            script += commit_script(f"pr{k}", mark, parent, files)
            parent = f":{mark}"
        heads.append(f"pr{k}")
    r = git(repo, "fast-import", "--quiet", stdin=script)
    assert r.returncode == 0, r.stderr
    return heads


def run_case(repo: Path, work: Path, seed: int) -> tuple[int, int]:
    """(PRs compared, PRs the queue ejected on a conflict); raises on any inequality."""
    rng = random.Random(seed)
    for ref in out(repo, "for-each-ref", "--format=%(refname)").split():
        git(repo, "update-ref", "-d", ref)
    heads = build(repo, rng, rng.randint(2, 4))
    q = out(repo, "rev-parse", "main")
    chain: list[str] = []
    for head in heads:
        merged = git(repo, "merge-tree", "--write-tree", q, head)
        if merged.returncode != 0:
            assert merged.returncode == 1, f"seed {seed}: merge-tree failed: {merged.stderr}"
            break
        q = out(repo, "commit-tree", merged.stdout.split()[0], "-p", q, "-m", "Q")
        chain.append(out(repo, "rev-parse", f"{q}^{{tree}}"))
    if work.exists():
        out(work, "checkout", "-q", "-f", "--detach", "main")
        out(work, "clean", "-qfdx")
    else:
        out(repo, "worktree", "add", "-q", "--detach", str(work), "main")
    for i, head in enumerate(heads):
        landed = git(work, "merge", "--squash", head)
        if i >= len(chain):
            assert landed.returncode != 0, f"seed {seed}: the squash of {head} is clean but the queue ejected it"
            return i, len(heads) - i
        assert landed.returncode == 0, f"seed {seed}: the queue accepted {head} but the squash conflicts"
        out(work, "commit", "-q", "--allow-empty", "-m", "squash")
        tree = out(work, "rev-parse", "HEAD^{tree}")
        assert tree == chain[i], f"seed {seed}: PR {i} tested tree {chain[i]} != landed tree {tree}"
    return len(heads), 0


@pytest.mark.parametrize("chunk", range(CHUNKS))
def test_squash_onto_moving_main_has_the_tree_of_the_queue_chain(workdir, chunk):
    repo, work = Path(workdir) / "r", Path(workdir) / "w"
    out(Path(workdir), "init", "-q", "-b", "main", str(repo))
    compared = ejected = 0
    for seed in range(chunk * CASES // CHUNKS, (chunk + 1) * CASES // CHUNKS):
        a, b = run_case(repo, work, seed)
        compared, ejected = compared + a, ejected + b
    assert compared > 0


def commit_file(repo: Path, name: str, lines: list[str], msg: str) -> None:
    (repo / name).write_text("\n".join(lines) + "\n")
    out(repo, "add", "-A")
    out(repo, "commit", "-q", "-m", msg)


def queue_vs_squash(repo: Path, heads: list[str]) -> tuple[list[str], list[str]]:
    """(queue trees, squash trees) of `heads` in order, on main of `repo`'s checkout."""
    q, queued = out(repo, "rev-parse", "main"), []
    for head in heads:
        q = out(repo, "commit-tree", out(repo, "merge-tree", "--write-tree", q, head), "-p", q, "-m", "Q")
        queued.append(out(repo, "rev-parse", f"{q}^{{tree}}"))
    out(repo, "checkout", "-q", "main")
    landed = []
    for head in heads:
        out(repo, "merge", "--squash", head)
        out(repo, "commit", "-q", "-m", "squash")
        landed.append(out(repo, "rev-parse", "HEAD^{tree}"))
    return queued, landed


def seeded(root: Path) -> Path:
    repo = root / "h"
    out(root, "init", "-q", "-b", "main", str(repo))
    commit_file(repo, "a.txt", [f"a {j}" for j in range(20)], "base")
    commit_file(repo, "b.txt", [f"b {j}" for j in range(20)], "base b")
    return repo


def test_a_rename_in_one_pr_and_an_edit_of_it_in_another_land_the_queue_tree(workdir):
    repo = seeded(Path(workdir))
    base = out(repo, "rev-parse", "HEAD")
    out(repo, "checkout", "-q", "-b", "ren", base)
    out(repo, "mv", "a.txt", "a2.txt")
    out(repo, "commit", "-q", "-m", "rename")
    out(repo, "checkout", "-q", "-b", "edit", base)
    commit_file(repo, "a.txt", [f"a {j}" if j != 7 else "edited" for j in range(20)], "edit")
    out(repo, "checkout", "-q", "-b", "next", base)
    commit_file(repo, "b.txt", [f"b {j}" if j != 3 else "other" for j in range(20)], "other")
    queued, landed = queue_vs_squash(repo, ["ren", "edit", "next"])
    assert queued == landed
    assert "edited" in out(repo, "show", "HEAD:a2.txt")


def test_a_criss_cross_history_has_the_same_tree_in_the_queue_and_on_main(workdir):
    repo = seeded(Path(workdir))
    base = out(repo, "rev-parse", "HEAD")
    for name, change in (("x", ("a.txt", 2, "x2")), ("y", ("b.txt", 15, "y15"))):
        out(repo, "checkout", "-q", "-b", name, base)
        lines = (repo / change[0]).read_text().splitlines()
        lines[change[1]] = change[2]
        commit_file(repo, change[0], lines, name)
    x_old, y_old = out(repo, "rev-parse", "x"), out(repo, "rev-parse", "y")
    out(repo, "checkout", "-q", "x")
    out(repo, "merge", "-q", "--no-edit", y_old)
    out(repo, "checkout", "-q", "y")
    out(repo, "merge", "-q", "--no-edit", x_old)
    for name in ("x", "y"):
        out(repo, "checkout", "-q", name)
        commit_file(repo, f"{name}_new.txt", [name], f"{name} tail")
    assert len(out(repo, "merge-base", "--all", "x", "y").split()) == 2
    out(repo, "checkout", "-q", "main")
    queued, landed = queue_vs_squash(repo, ["x", "y"])
    assert queued == landed
