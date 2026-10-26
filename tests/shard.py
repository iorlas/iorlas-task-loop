"""Split the suite across CI shards: python tests/shard.py run INDEX COUNT runs shard INDEX (1-based) of COUNT.

Every test is in exactly one shard. Units (a class, or a chunk of a big one) are placed heaviest first on the lightest shard (weight: its test
count, times WEIGHT for a module whose tests are slow), ties broken by name, so the split is stable for a given tree.
`python tests/shard.py run INDEX COUNT` runs it. `python tests/shard.py --check COUNT` fails when a test would run in no shard or in two.

The release gate (dev/release.py) uses the same split on one machine: `plan COUNT --root DIR` prints {"shards": [[id]], "serial": [id]},
the tests named in SERIAL left out of the shards; `ids FILE --root DIR` runs the ids listed in FILE (one per line) in this process.
"""
import argparse
import json
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# module -> seconds per test, measured on a Mac with 14 shards at once (a module not listed counts 0.3): what a test costs sets which shard it joins.
WEIGHT = {"test_engine": 3.7, "test_stages": 3.1, "test_look": 5.3, "test_checks_speed": 2.1, "test_trace_records": 5.1, "test_release": 4.3,
          "test_verify_noblock": 3.3, "test_doctor": 0.9, "test_slot_git": 0.95, "test_land_lock": 1.5, "test_held_branch": 0.55}
DEFAULT_WEIGHT = 0.3

# Tests that must not share a clock, a port, a lock or a process group with another test running at the same moment, so the release gate
# runs them in ONE process after the parallel shards. (module, class or None for the whole module, reason); found by measurement and by
# reading the code, not guessed: a module is listed only with the reason that makes it unsafe beside others.
SERIAL = (
    ("test_race", None, "races real processes on one repo and SIGKILLs them (os.kill / killpg of started PIDs); its timing windows need a quiet machine"),
    ("test_write_idle", None, "starts real worker process groups and asserts how long a writer stays idle against the wall clock; load moves the clock"),
)


BIG = 60    # a class with more tests than this is cut into chunks of CHUNK tests (test_engine.EngineTest alone is a fifth of the suite)
CHUNK = 40


def tests(root=HERE):
    """{unit: [test id]}: a small class is one unit, a big one is several."""
    by_class = {}
    suite = unittest.defaultTestLoader.discover(str(root), top_level_dir=str(root))

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                by_class.setdefault("%s.%s" % (type(t).__module__, type(t).__name__), []).append(t.id())
    walk(suite)
    units = {}
    for cls, ids in by_class.items():
        ids.sort()
        if len(ids) > BIG:
            k = -(-len(ids) // CHUNK)
            for j in range(k):  # every k-th test: slow neighbours (same name prefix) land in different chunks
                units["%s#%d" % (cls, j)] = ids[j::k]
        else:
            units[cls] = ids
    return units


def is_serial(test_id, serial=SERIAL):
    module, cls = (test_id.split(".") + [""])[:2]
    return any(m == module and c in (None, cls) for m, c, _ in serial)


def split(count, root=HERE, serial=()):
    """count shards of every test not in `serial` (a SERIAL-shaped tuple; none by default: CI runs everything)."""
    units = {u: ids for u, ids in tests(root).items() if not is_serial(ids[0], serial)}
    weight = {u: len(ids) * WEIGHT.get(u.split(".")[0], DEFAULT_WEIGHT) for u, ids in units.items()}
    shards, load = [[] for _ in range(count)], [0] * count
    for u in sorted(units, key=lambda u: (-weight[u], u)):
        i = load.index(min(load))
        shards[i].extend(units[u])
        load[i] += weight[u]
    return shards


def plan(count, root=HERE, serial=SERIAL):
    """{"shards": count lists of test ids, "serial": the ids of SERIAL, sorted}: every test once."""
    return {"shards": split(count, root, serial),
            "serial": sorted(t for ids in tests(root).values() for t in ids if is_serial(t, serial))}


class Timed(unittest.TextTestResult):
    """A result that remembers how long each test took (seconds, by id)."""
    def startTest(self, test):
        self.t0 = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.times[test.id()] = time.monotonic() - self.t0


def run_ids(ids, times=None):
    class Result(Timed):
        pass
    Result.times = {}
    res = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromNames(ids))
    if times:
        Path(times).write_text(json.dumps(Result.times), encoding="utf-8")
    return res


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd in ("plan", "ids"):
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("arg")
        ap.add_argument("--root", default=str(HERE))
        ap.add_argument("--times")
        a = ap.parse_args()
        sys.path.insert(0, a.root)
        if cmd == "plan":
            print(json.dumps(plan(int(a.arg), Path(a.root))))
            sys.exit(0)
        ids = [l for l in Path(a.arg).read_text(encoding="utf-8").splitlines() if l.strip()]
        sys.exit(0 if run_ids(ids, a.times).wasSuccessful() else 1)
    if cmd == "--check":
        count = int(sys.argv[2])
        placed = [t for s in split(count) for t in s]
        every = [t for ids in tests().values() for t in ids]
        assert sorted(placed) == sorted(every) and len(placed) == len(set(placed)), "a test is in no shard or in two"
        files = {p.stem for p in HERE.glob("test_*.py")}
        assert not files - {t.split(".")[0] for t in placed}, "no test from %s" % sorted(files - {t.split(".")[0] for t in placed})
        print("ok: %d tests in %d shards (%s)" % (len(placed), count, ", ".join(str(len(s)) for s in split(count))))
        p = plan(count)
        assert sorted([t for s in p["shards"] for t in s] + p["serial"]) == sorted(placed), "the release plan loses or doubles a test"
        for m, c, why in SERIAL:
            assert any(t.split(".")[0] == m and c in (None, t.split(".")[1]) for t in placed), "SERIAL names %s.%s, no such test" % (m, c)
            assert why.strip(), "SERIAL %s has no reason" % m
    else:  # run INDEX COUNT
        ids = split(int(sys.argv[3]))[int(sys.argv[2]) - 1]
        res = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(ids))
        sys.exit(0 if res.wasSuccessful() else 1)
