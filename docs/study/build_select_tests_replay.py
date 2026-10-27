#!/usr/bin/env python3
"""Build RECORDS.json for the 50-landing replay of tools/select_tests.py (read-only on git, offline).

Landing = a version-bump commit on the first-parent history of origin/main ("0.N.M: ...").
base = the previous bump commit; landed = this bump commit; paths = `git diff --name-status -M`
from base to the commit just before the bump (the work), because the bump itself always
touches .claude-plugin/plugin.json, which the selector maps to the whole suite.
inventory = unittest ids discovered (`discover -s tests`) in an exported tree of the landed sha.
failures = red check/gate/release-suite rounds recovered from the engine logs (see attribute()).
Usage: build_select_tests_replay.py WORKDIR OUT.json
"""
import json, os, re, subprocess, sys, glob, bisect, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.expanduser("~/.config/task-loop")
BUMP = re.compile(r"^\d+\.\d+\.\d+:")

def git(*a):
    return subprocess.check_output(("git", "-C", ROOT) + a, text=True)

def bumps():
    out = []
    for line in git("log", "--first-parent", "--format=%H %ct %s", "origin/main").splitlines():
        sha, ct, subj = line.split(" ", 2)
        if BUMP.match(subj):
            out.append((sha, int(ct), subj))
        if len(out) == 51:
            break
    return list(reversed(out))  # oldest first

def paths(base, work):
    res = []
    for line in git("diff", "--name-status", "-M", base, work).splitlines():
        cols = line.split("\t")
        res.extend(cols[1:])  # both sides of a rename
    return sorted(set(res))

LISTER = r'''
import sys, unittest
suite = unittest.TestLoader().discover("tests", top_level_dir="tests")
def walk(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): yield from walk(t)
        else: yield t
ids = [t.id() for t in walk(suite)]
bad = [i for i in ids if "_FailedTest" in i or "ModuleImportFailure" in i]
import json; print(json.dumps({"ids": ids, "bad": bad}))
'''

def inventory(sha, work):
    d = os.path.join(work, sha[:12])
    os.makedirs(d, exist_ok=True)
    subprocess.check_call("git -C %s archive %s | tar -x -C %s" % (ROOT, sha, d), shell=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=d)
    r = subprocess.run([sys.executable, "-c", LISTER], cwd=d, env=env, capture_output=True, text=True, timeout=600)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    return sorted(set(out["ids"])), out["bad"], r.returncode

ID = re.compile(r"^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)")

def red_ids(path):
    ids = {}
    try:
        text = open(path, errors="replace").read()
    except OSError:
        return ids
    for line in text.splitlines():
        m = ID.match(line)
        if m:
            tid = m.group(2)  # mod.Class.test
            ids[tid] = line.split(":")[0]
    return ids

def red_rounds():
    """(kind, source, timestamp, run-or-None, {id: FAIL|ERROR}) for every red log of this repo."""
    rows = []
    for f in sorted(glob.glob(CFG + "/releases/suite-*.log")):
        m = re.match(r"suite-(\d{8})-(\d{6})-", os.path.basename(f))
        ts = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
        ids = red_ids(f)
        if ids:
            rows.append(("release-suite", "releases/" + os.path.basename(f), ts, None, ids))
    landed_runs = {}
    for line in open(CFG + "/traces.jsonl"):
        d = json.loads(line)
        if "task-loop" in d.get("repo", "") and d.get("outcome") == "landed":
            landed_runs[d["run"]] = d["sha"]
    for run, sha in landed_runs.items():
        for f in sorted(glob.glob("%s/runs/%s/checks/*.log" % (CFG, run)) + glob.glob("%s/runs/%s/gate.r*.log" % (CFG, run))):
            ids = red_ids(f)
            if ids:
                kind = "gate-round" if "/gate." in f else "check-round"
                rows.append((kind, "runs/%s/%s" % (run, os.path.relpath(f, CFG + "/runs/" + run)), None, run, ids, sha))
    return rows

def main(work, out):
    bl = bumps()
    shas = [b[0] for b in bl]
    landings = []
    for i in range(1, 51):
        (bsha, _, _), (lsha, lct, subj) = bl[i - 1], bl[i]
        work_tip = git("rev-parse", lsha + "^").strip()
        landings.append({"id": "landing-%03d" % i, "order": i, "base": bsha, "landed": lsha,
                         "version": subj.split(":")[0], "subject": subj,
                         "work_tip": work_tip, "landed_time": lct,
                         "paths": paths(bsha, work_tip), "failures": [], "errors": [],
                         "red_sources": []})
    with ThreadPoolExecutor(max_workers=8) as ex:
        invs = list(ex.map(lambda l: inventory(l["landed"], work), landings))
    for l, (inv, bad, rc) in zip(landings, invs):
        if bad or not inv:
            raise SystemExit("inventory failed at %s: %s rc=%s" % (l["landed"], bad[:3], rc))
        l["inventory"] = inv
    # attribution
    cut = [l["landed_time"] for l in landings]
    unattributed = []
    def put(l, tid, kind, src, how):
        key = "failures" if kind == "FAIL" else "errors"
        if tid in l["inventory"]:
            if tid not in l[key]:
                l[key].append(tid)
            l["red_sources"].append({"id": tid, "source": src, "how": how})
        else:
            unattributed.append({"id": tid, "source": src, "landing": l["id"], "why": "id absent from the landed inventory"})
    for row in red_rounds():
        if row[0] == "release-suite":
            _, src, ts, _, ids = row
            # a red release suite precedes the first landing at or after it
            k = bisect.bisect_left(cut, ts)
            how = "release suite red before this landing (next landing after the log time)"
            # release attempts are not ordered like landings: move on to the first landing whose
            # inventory holds every red id of the log (the branch under test introduced them)
            j = k
            while j < len(landings) and j < k + 3 and not set(ids) <= set(landings[j]["inventory"]):
                j += 1
            if j < len(landings) and j < k + 3:
                if j != k:
                    how += "; moved +%d landing(s): the red ids first exist there" % (j - k)
                k = j
        else:
            _, src, _, run, ids, sha = row
            full = git("rev-parse", sha).strip()
            k = None
            for j, l in enumerate(landings):  # first bump containing the run's landed commit
                if subprocess.call(["git", "-C", ROOT, "merge-base", "--is-ancestor", full, l["landed"]]) == 0:
                    k = j; break
            how = "red %s of a run that landed %s" % (row[0], sha[:9])
        if k is None or k >= len(landings):
            for tid in ids: unattributed.append({"id": tid, "source": src, "why": "outside the 50-landing window"})
            continue
        for tid, kind in ids.items():
            put(landings[k], tid, kind, src, how)
    json.dump({"provenance": {
        "repo": "iorlas-task-loop", "history": "git log --first-parent origin/main, 51 version-bump commits (0.22.3 .. 0.23.58)",
        "inventory": "unittest discover -s tests on `git archive <landed>` (no test body run)",
        "failures": "FAIL/ERROR lines in ~/.config/task-loop/{releases/suite-*.log, runs/<run>/checks/*.log, runs/<run>/gate.r*.log}; paths relative, no tokens",
        "unattributed_red": unattributed},
        "landings": landings}, open(out, "w"), indent=1, sort_keys=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
