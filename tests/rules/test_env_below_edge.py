"""Code below the edge takes an `Env` instead of reading the live process: a ratchet on the calls that still do.

A call is `ambient(`, `ambient_bead(`, `ambient_set(` or `snapshot(` of taskloop.contracts.env.
tests/rules/env_ratchet.json records the count per file; a count above its record fails (a new read of the
live process), and a count below it fails too until the record is lowered (a freed slot cannot be spent again). The edges (tl.py, the
dev scripts, the dashboard's command line, the hook entry) take the snapshot once and are not counted. A real Spawner is built only at an
edge and handed down (SPAWNER_EDGES). The same holds for the rest of what the process is: a real Git or Spawner is never a module-level
constant (a `REAL = RealGit(...)` default), the Identity is built only where an Env is taken or made (IDENTITY_SITES), and an exec
hand-over (TL_REEXEC, TL_LOOP_STATE, TL_RELEASE_REEXEC) is written only through childenv.exec_env.
"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path(__file__).with_name("env_ratchet.json")
EDGE = frozenset({"src/taskloop/contracts/env.py", "src/taskloop_dash/cli/dash.py",  # the owner of os.environ, and the dashboard's edge
                  "src/taskloop/hook/session.py", "src/taskloop/adapters/container_run.py"})  # the hooks' edge, and a script run by path
CALL = re.compile(r"\b(?:penv\.)?(?:ambient|ambient_bead|ambient_set|snapshot)\(")
NOT_ENV = re.compile(r"\b(?:looks|bf|cfg|self|snap)\.snapshot\(|def snapshot|def ambient")


def count_source(text: str) -> int:
    return sum(1 for line in text.splitlines() for m in CALL.finditer(line) if not NOT_ENV.search(line))


def count_tree(root: Path = ROOT) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "_vendor" in rel or rel in EDGE:
            continue
        n = count_source(path.read_text(encoding="utf-8"))
        if n:
            out[rel] = n
    return out


def problems(actual: dict[str, int], recorded: dict[str, int]) -> list[str]:
    out = []
    for rel in sorted(set(actual) | set(recorded)):
        a, r = actual.get(rel, 0), recorded.get(rel, 0)
        if a > r:
            out.append(f"{rel}: {a} reads of the live process, record {r}: take an Env parameter instead")
        elif a < r:
            out.append(f"{rel}: {a} reads, record {r}: lower tests/rules/env_ratchet.json to {a}")
    return out

BUILDS_SPAWNER = re.compile(r"\breal\.spawner\(|\bRealSpawner\(")
SPAWNER_EDGES = ("src/taskloop/cli/", "src/taskloop/adapters/spawner.py", "src/taskloop/app/wire/real.py",
                 "src/taskloop/app/launch/selftest.py")  # selftest: the sandbox's own env is a new edge; tl.py, dev/ are outside src


def spawner_builders(root: Path = ROOT) -> list[str]:
    """The files under src/ that build a real Spawner and are not an edge: they must take one as an argument."""
    out = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "_vendor" not in rel and not rel.startswith(SPAWNER_EDGES) and BUILDS_SPAWNER.search(path.read_text(encoding="utf-8")):
            out.append(rel)
    return out


AMBIENT_PORT = re.compile(r"^[A-Za-z_]\w*\s*(?::[^=\n]+)?=\s*(?:\w+\.)?(?:Real\w*|real\.(?:git|spawner))\(", re.M)
IDENTITY_CALL = re.compile(r"\bident\.identity\(|\bidentity\(")
IDENTITY_SITES = frozenset({"src/taskloop/adapters/ident.py", "src/taskloop/app/run/entry.py", "src/taskloop/app/launch/loop.py",
                            "src/taskloop/app/release/flow.py", "src/taskloop/app/launch/selftest.py"})  # each holds or makes an Env
HANDOVERS = "TL_REEXEC|TL_LOOP_STATE|TL_RELEASE_REEXEC"
HANDOVER_NAME = re.compile(rf"EnvVar\.(?:{HANDOVERS})\b|[\"'](?:{HANDOVERS})[\"']")
HANDOVER_OK = re.compile(r"\.get\(EnvVar\.|exec_env\(|\bEnvVar\.\w+\.value: \w+")  # a read of it, the one writer, a child's `extra`
HANDOVER_FILES = ("src/taskloop/contracts/envvars.py", "src/taskloop/adapters/childenv.py")


def ambient_ports(text: str) -> list[str]:
    """Module-level `NAME = RealGit(...)` / `real.git(...)` / `RealSpawner(...)`: a port built at import, from whatever the process has."""
    return [m.group(0) for m in AMBIENT_PORT.finditer(text)]


def stray_handovers(text: str) -> list[str]:
    """The lines that name an exec hand-over other than to read it, to hand it to exec_env, or to put it in a child's extra."""
    return [ln.strip() for ln in text.splitlines()
            if HANDOVER_NAME.search(ln) and not HANDOVER_OK.search(ln) and not ln.lstrip().startswith(("#", '"""'))]


def rule_breaks(root: Path = ROOT) -> list[str]:
    out = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "_vendor" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        out += [f"{rel}: module-level port {m}" for m in ambient_ports(text)]
        if rel not in IDENTITY_SITES and IDENTITY_CALL.search(text):
            out.append(f"{rel}: builds an Identity below the edge: take one as an argument")
        if rel not in HANDOVER_FILES:
            out += [f"{rel}: writes an exec hand-over outside childenv.exec_env: {ln}" for ln in stray_handovers(text)]
    return out


class EnvBelowTheEdge(unittest.TestCase):
    def test_no_file_reads_the_process_more_than_its_record(self):
        recorded = json.loads(RECORD.read_text(encoding="utf-8"))
        self.assertEqual(problems(count_tree(), recorded), [])

    def test_only_an_edge_builds_a_real_spawner(self):
        self.assertEqual(spawner_builders(), [])

    def test_a_spawner_built_below_the_edge_is_seen(self):
        self.assertTrue(BUILDS_SPAWNER.search("spawn = real.spawner(env)"))
        self.assertTrue(BUILDS_SPAWNER.search("x = RealSpawner(env)"))

    def test_no_module_level_port_no_identity_below_the_edge_no_stray_hand_over(self):
        self.assertEqual(rule_breaks(), [])

    def test_a_planted_ambient_port_identity_or_hand_over_is_seen(self):
        self.assertTrue(ambient_ports("REAL: Final = RealGit(penv.snapshot())\n"))
        self.assertTrue(ambient_ports("SPAWN = real.spawner(env)\n"))
        self.assertFalse(ambient_ports("    git = real.git(env)\n"))
        self.assertTrue(IDENTITY_CALL.search("who = ident.identity(env)"))
        self.assertTrue(stray_handovers('os.environ["TL_REEXEC"] = text\n'))
        self.assertTrue(stray_handovers("penv.export(EnvVar.TL_LOOP_STATE, raw)\n"))
        self.assertFalse(stray_handovers("Reexec.parse(env.get(EnvVar.TL_REEXEC))\n"))
        self.assertFalse(stray_handovers("childenv.exec_env(env, {EnvVar.TL_RELEASE_REEXEC: '1'})\n"))

    def test_a_planted_read_fails(self):
        self.assertEqual(count_source("x = penv.snapshot().vars\n"), 1)
        self.assertTrue(problems({"a.py": 2}, {"a.py": 1}))
        self.assertTrue(problems({"a.py": 1}, {"a.py": 2}))
        self.assertTrue(problems({"new.py": 1}, {}))
        self.assertEqual(problems({"a.py": 1}, {"a.py": 1}), [])


if __name__ == "__main__":
    unittest.main()
