"""Split the suite across CI shards: python tests/shard.py run INDEX COUNT runs shard INDEX (1-based) of COUNT.

Every test is in exactly one shard. Units (a class, or a chunk of a big one) are placed heaviest first on the lightest shard (weight: the sum of its tests' measured seconds in tests/durations.json), ties broken by name, so the split is stable for a given tree.
`python tests/shard.py run INDEX COUNT` runs it. `python tests/shard.py --check COUNT` fails when a test would run in no shard or in two.

The release gate (dev/release.py) uses the same split on one machine: `plan COUNT --root DIR` prints {"shards": [[id]], "serial": [id]},
the tests named in SERIAL left out of the shards; `ids FILE --root DIR [--times F] [--parent PID] [--max-mb MB]` runs the ids listed in FILE (one per line) in this process.
"""
import argparse
import json
import os
import signal
import sys
import time
import unittest
from typing import Any
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
DEFAULT_WEIGHT = 0.3  # seconds a test costs when tests/durations.json has no entry for it (a new test)
DURATIONS = HERE / "durations.json"  # {test id: seconds}, measured by `python3 dev/suite.py --record`; a test not in it counts DEFAULT_WEIGHT


def load_durations(root=HERE):
    """{test id: seconds} from durations.json next to the tests of `root` (empty when absent or unreadable)."""
    try:
        return json.loads((Path(root) / "durations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cost(test_id, durations):
    """What a test costs the shard that runs it: its measured seconds, else DEFAULT_WEIGHT."""
    d = durations.get(test_id)
    return d if isinstance(d, (int, float)) else DEFAULT_WEIGHT

# Tests that must not share a clock, a port, a lock or a process group with another test running at the same moment, so the release gate
# runs them in ONE process after the parallel shards. (module, class or None for the whole module, reason); found by measurement and by
# reading the code, not guessed: a module is listed only with the reason that makes it unsafe beside others.
SERIAL = (
    ("test_write_idle", None, "starts real worker process groups and asserts how long a writer stays idle against the wall clock; load moves the clock"),
)


BIG = 60    # a class with more tests than this is cut into chunks of CHUNK tests (test_engine.EngineTest alone is a fifth of the suite)
CHUNK = 40


def tests(root=HERE):
    """{unit: [test id]}: a small class is one unit, a big one is several (dealt so the chunks cost about the same)."""
    durations = load_durations(root)
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
            chunks, load = [[] for _ in range(k)], [0.0] * k
            for t in sorted(ids, key=lambda t: (-cost(t, durations), t)):  # heaviest first onto the lightest chunk
                j = load.index(min(load))
                chunks[j].append(t)
                load[j] += cost(t, durations)
            for j, c in enumerate(chunks):
                units["%s#%d" % (cls, j)] = sorted(c)
        else:
            units[cls] = ids
    return units


def is_serial(test_id, serial=SERIAL):
    module, cls, name = (test_id.split(".") + ["", ""])[:3]
    return any(m == module and c in (None, cls, cls + "." + name) for m, c, _ in serial)


def split(count, root=HERE, serial=()):
    """count shards of every test not in `serial` (a SERIAL-shaped tuple; none by default: CI runs everything)."""
    units = {u: [t for t in ids if not is_serial(t, serial)] for u, ids in tests(root).items()}
    units = {u: ids for u, ids in units.items() if ids}
    durations = load_durations(root)
    weight = {u: sum(cost(t, durations) for t in ids) for u, ids in units.items()}
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
    times: dict[str, float] = {}
    t0 = 0.0

    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)

    def startTest(self, test):
        self.t0 = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.times[test.id()] = time.monotonic() - self.t0


def exit_with_parent(parent, every=1.0):
    """Leave this process once its parent `parent` (the launcher's pid) is gone: nobody reads this shard's result, and an orphan that
    holds gigabytes helps no one. A timer signal, not a watcher thread: with a second thread alive, this suite's shards grew from ~150 MB
    to 2-3 GB (measured). (An EOF on a pipe from the launcher would say the same, but stream-proc's run gives a child /dev/null for stdin.)
    os._exit: no cleanup can hang on a dead parent."""
    def check(_signum, _frame):
        if os.getppid() != parent:
            os._exit(3)
    check(0, None)
    signal.signal(signal.SIGALRM, check)
    signal.setitimer(signal.ITIMER_REAL, every, every)


def cap_memory(megabytes):
    """Linux only (macOS does not enforce RLIMIT_AS): cap this process's address space, and its children's each, at `megabytes`, never
    raising an existing lower cap. A runaway test gets MemoryError (red, in the suite log) instead of starving the host. A healthy
    shard's address space peaks near 430 MB (resident ~250), so the release gate's 2048 MB budget leaves 5x."""
    limit = megabytes << 20
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if sys.platform.startswith("linux") and (soft == resource.RLIM_INFINITY or soft > limit):
            resource.setrlimit(resource.RLIMIT_AS, (limit if hard == resource.RLIM_INFINITY else min(limit, hard), hard))
    except (ImportError, OSError, ValueError):
        pass


def run_ids(ids, times=None):
    class Result(Timed):
        pass
    Result.times = {}  # this run's own table, not Timed's
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
        ap.add_argument("--max-mb", type=int, default=0, help="cap this process's address space (Linux), in MB")
        ap.add_argument("--parent", type=int, default=0, help="exit when this pid is no longer this process's parent")
        a = ap.parse_args()
        sys.path.insert(0, a.root)
        if cmd == "plan":
            print(json.dumps(plan(int(a.arg), Path(a.root))))
            sys.exit(0)
        if a.max_mb:
            cap_memory(a.max_mb)
        if a.parent:  # the release gate's pid: its death ends this shard (see exit_with_parent)
            exit_with_parent(a.parent)
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
            assert any(is_serial(t, ((m, c, why),)) for t in placed), "SERIAL names %s.%s, no such test" % (m, c)
            assert why.strip(), "SERIAL %s has no reason" % m
    else:  # run INDEX COUNT
        ids = split(int(sys.argv[3]))[int(sys.argv[2]) - 1]
        res = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(ids))
        sys.exit(0 if res.wasSuccessful() else 1)
