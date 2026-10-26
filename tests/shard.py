"""Split the suite across CI shards: python tests/shard.py run INDEX COUNT runs shard INDEX (1-based) of COUNT.

Every test is in exactly one shard. Units (a class, or a chunk of a big one) are placed heaviest first on the lightest shard (weight: its test
count, times WEIGHT for a module whose tests are slow), ties broken by name, so the split is stable for a given tree.
`python tests/shard.py run INDEX COUNT` runs it. `python tests/shard.py --check COUNT` fails when a test would run in no shard or in two.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WEIGHT = {}  # module -> factor for slow tests; set from measured CI times


BIG = 60    # a class with more tests than this is cut into chunks of CHUNK tests (test_engine.EngineTest alone is a fifth of the suite)
CHUNK = 40


def tests():
    """{unit: [test id]}: a small class is one unit, a big one is several."""
    by_class = {}
    suite = unittest.defaultTestLoader.discover(str(HERE), top_level_dir=str(HERE))

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
            for n in range(0, len(ids), CHUNK):
                units["%s#%d" % (cls, n // CHUNK)] = ids[n:n + CHUNK]
        else:
            units[cls] = ids
    return units


def split(count):
    units = tests()
    weight = {u: len(ids) * WEIGHT.get(u.split(".")[0], 1) for u, ids in units.items()}
    shards, load = [[] for _ in range(count)], [0] * count
    for u in sorted(units, key=lambda u: (-weight[u], u)):
        i = load.index(min(load))
        shards[i].extend(units[u])
        load[i] += weight[u]
    return shards


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "--check":
        count = int(sys.argv[2])
        placed = [t for s in split(count) for t in s]
        every = [t for ids in tests().values() for t in ids]
        assert sorted(placed) == sorted(every) and len(placed) == len(set(placed)), "a test is in no shard or in two"
        files = {p.stem for p in HERE.glob("test_*.py")}
        assert not files - {t.split(".")[0] for t in placed}, "no test from %s" % sorted(files - {t.split(".")[0] for t in placed})
        print("ok: %d tests in %d shards (%s)" % (len(placed), count, ", ".join(str(len(s)) for s in split(count))))
    else:  # run INDEX COUNT
        ids = split(int(sys.argv[3]))[int(sys.argv[2]) - 1]
        res = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(ids))
        sys.exit(0 if res.wasSuccessful() else 1)
