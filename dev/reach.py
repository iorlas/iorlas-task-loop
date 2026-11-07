"""How far a change reaches: the tests `dev/affected.py` selects per recent commit, the single files that select half the suite, and the
stage-to-stage import edges that run both ways. The measurement behind docs/design/architecture-vertical.md; run it before and after a
move to see whether the reach fell.

    python3 dev/reach.py [--root DIR] [--commits N]      prints the summary, the wide-alone files and the two-way stage pairs

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

STAGES = {
    "run": "shell", "launch": "shell", "prune": "shell", "wire": "shell", "loop": "shell",
    "plan": "work", "write": "work", "review": "work", "look": "work", "artifacts": "work", "prompts": "work",
    "workers": "workers", "checks": "gate", "land": "land", "release": "release", "reconcile": "release", "slots": "slots", "asks": "asks",
    "report": "report", "track": "track", "doctor": "doctor", "lanes": "delegate-glue", "beads": "beads", "layout": "store",
}
TOP = {"tldash": "dash", "delegate": "delegate", "hook": "hook", "cli": "cli", "stores": "store"}


def stage_of(path):
    """The stage a src file belongs to by its folder (app/<slice>, domain/<slice>, a top-level package), else 'kernel'."""
    parts = path.split("/")
    if parts[0] == "packages" and parts[2:3] == ["src"] and parts[1] in {"dash", "kernel", "slots"}:
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


def commit_files(root, count):
    """The first-parent commits of origin/main (else HEAD), newest first, as sets of changed paths."""
    log = subprocess.run(["git", "-C", str(root), "log", "--first-parent", "-n", str(count), "--format=%H", "origin/main"],
                         capture_output=True, text=True, check=False).stdout.split()
    out = []
    for sha in log:
        diff = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--no-renames", sha + "^", sha],
                              capture_output=True, text=True, check=False).stdout.split()
        out.append(set(diff))
    return out


def report(root, count):
    repo = Repo(root)
    total = len([p for p in repo.trees if is_test(p)])
    changes = [{f for f in files if f in repo.trees} for files in commit_files(root, count)]
    changes = [c for c in changes if c]
    counts = [len(select(repo, c)) for c in changes]
    lines = [f"tests {total}, commits measured {len(changes)}"]
    lines.append("selected per commit: " + ", ".join(f"{k} {v}" for k, v in summary(counts).items()) if counts else "no commit to measure")
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
    args = ap.parse_args(argv)
    print(report(args.root, args.commits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
