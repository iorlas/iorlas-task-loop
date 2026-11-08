"""How far a change reaches: the tests `dev/affected.py` selects per recent commit, the single files that select half the suite, and the
stage-to-stage import edges that run both ways. The measurement behind docs/design/architecture-vertical.md; run it before and after a
move to see whether the reach fell.

    python3 dev/reach.py [--root DIR] [--commits N] [--until REV] [--wide]
    prints the summary, the wide-alone files and the two-way stage pairs

Selection of an old commit uses the graph of the checkout as it is now (an approximation of what the gate selected then). Standard library
only; the stage table below is the doc's mapping by folder name and is the one thing to edit when a stage is carved."""
import argparse
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from affected import Repo, is_test, select
from packages import reached

STAGES = {
    "run": "shell", "launch": "shell", "prune": "shell", "wire": "shell", "loop": "shell",
    "plan": "work", "write": "work", "review": "work", "look": "work", "artifacts": "work", "prompts": "work",
    "workers": "workers", "checks": "gate", "land": "land", "release": "release", "reconcile": "release", "slots": "slots", "asks": "asks",
    "report": "report", "track": "track", "doctor": "doctor", "accounts": "delegate-glue", "beads": "beads", "layout": "store",
}
TOP = {"tldash": "dash", "delegate": "delegate", "hook": "hook", "cli": "cli", "stores": "store"}


def stage_of(path):
    """Map source folders to stages; carved plan, review, look and write all belong to the work package."""
    parts = path.split("/")
    if len(parts) > 2 and parts[0] == "packages" and parts[2] == "src" and parts[1] in {
        "land", "dash", "kernel", "slots", "work", "release",
    }:
        return parts[1]
    if parts[0] != "src":
        return None
    if parts[1] != "taskloop":
        return TOP.get(parts[1], parts[1])
    if len(parts) > 3 and parts[2] in ("app", "domain"):
        return STAGES.get(parts[3].removesuffix(".py"), "kernel")
    return TOP.get(parts[2], "kernel")


def summary(counts):
    """Median, mean, p90 and max of the numbers of tests selected per change."""
    ordered = sorted(counts)
    return {"median": statistics.median(ordered), "mean": round(statistics.mean(ordered)), "p90": ordered[int(len(ordered) * 0.9)],
            "max": ordered[-1]}


def wide_alone(repo, files, total):
    """The files among `files` that on their own select at least half of the `total` tests."""
    return [f for f in sorted(files) if len(select(repo, {f})) * 2 >= total]


def stage_edges(repo):
    """{(from stage, to stage): number of direct src import edges} between different stages."""
    edges = Counter()
    for path, targets in repo.edges.items():
        for target in targets:
            a, b = stage_of(path), stage_of(target)
            if a and b and a != b:
                edges[(a, b)] += 1
    return edges


def two_way(edges):
    """The stage pairs that import each other, with both counts ('kernel' is the catch-all, not a stage: left out)."""
    return sorted((a, b, n, edges[(b, a)]) for (a, b), n in edges.items() if a < b and (b, a) in edges and "kernel" not in (a, b))


def commits(root, count, until):
    """First-parent window ending at until, newest first, with identity and changed paths."""
    log = subprocess.run(["git", "-C", str(root), "log", "--first-parent", "-n", str(count),
                          "--format=%h%x09%cs%x09%s", until],
                         capture_output=True, text=True, check=True).stdout.splitlines()
    out = []
    for line in log:
        sha, date, subject = line.split("\t", 2)
        diff = subprocess.run(["git", "-C", str(root), "diff-tree", "--root", "--no-commit-id", "-r",
                               "--name-only", "--no-renames", "--first-parent", "-m", sha],
                              capture_output=True, text=True, check=True).stdout.splitlines()
        out.append((sha, date, subject, set(diff)))
    return out


def package_summary(root, changes):
    """Whole package suite inventory, separate from shell file selection."""
    sizes = {p.parent.name: sum(1 for f in p.rglob("test_*.py") if f.is_file())
             for p in (Path(root) / "packages").glob("*/tests") if p.is_dir()}
    suites = [reached(Path(root), c) for c in changes]
    counts = [len(s) for s in suites]
    files = [sum(sizes.get(name, 0) for name in s) for s in suites]
    return ("package suites selected (run whole, not counted above): " +
            (f"median {statistics.median(counts)}, max {max(counts)}; test files median {statistics.median(files)}"
             if counts else "no commit to measure"))


def report(root, count, until="HEAD", wide=False):
    repo = Repo(root)
    total = len([p for p in repo.trees if is_test(p)])
    window = commits(root, count, until)
    measured = [(sha, date, subject, files) for sha, date, subject, files in window if files & repo.trees.keys()]
    changes = [files & repo.trees.keys() for _, _, _, files in measured]
    rules = {p for p in select(repo, set()) if p.startswith("tests/rules/")}
    selections = [select(repo, c) for c in changes]
    counts = [len(selected) for selected in selections]
    beyond = [len(set(selected) - rules) for selected in selections]
    lines = [f"tests {total}, commits measured {len(changes)}"]
    lines.append("selected per commit: " + ", ".join(f"{k} {v}" for k, v in summary(counts).items()) if counts else "no commit to measure")
    lines.append(f"beyond the always-run tests/rules ({len(rules)} files): " + (
        ", ".join(f"{k} {v}" for k, v in summary(beyond).items()) if beyond else "no commit to measure"))
    lines.append("shell test files (root tests/ only)")
    if window:
        lines.append(f"window: {len(window)} commits ending at {window[0][0]} {window[0][1]}")
    lines.append(package_summary(root, [files for _, _, _, files in measured]))
    if wide:
        lines.append("wide commits ranked by shell test files selected:")
        ranked = sorted(zip(measured, counts, strict=True), key=lambda item: -item[1])
        lines += [f"  {sha} {subject}: {n}/{total}" for (sha, _, subject, _), n in ranked if n * 2 >= total]
    wide = Counter(f for c, n in zip(changes, counts, strict=True) if n * 2 >= total for f in wide_alone(repo, c, total))
    lines.append(f"wide commits {sum(1 for n in counts if n * 2 >= total)}; files that alone select half, by commits:")
    lines += [f"  {n:3d} {f}" for f, n in wide.most_common(15)]
    lines.append("stage pairs importing each other (a<->b, edges a->b / b->a):")
    lines += [f"  {a} <-> {b}  {x} / {y}" for a, b, x, y in two_way(stage_edges(repo))]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reach.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--commits", type=int, default=120)
    ap.add_argument("--until", default="HEAD", help="end the first-parent window at REV (default: HEAD)")
    ap.add_argument("--wide", action="store_true", help="list wide commits ranked by shell selection")
    args = ap.parse_args(argv)
    if args.commits < 1:
        ap.error("--commits must be positive")
    print(report(args.root, args.commits, args.until, args.wide))
    return 0


if __name__ == "__main__":
    sys.exit(main())
