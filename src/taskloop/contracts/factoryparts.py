"""factory.db as the parts that own its tables (stage-isolation 3.1): today's schema declared at version 1, each part by its future owner.

The tables stay here until their stage's own store module defines them (the D-* beads of ARCHVERT); every table is in exactly one part.
`kv` is the prefix grab-bag the D-KV bead takes apart. The frozen `user_version` (factorydb.SCHEMA_VERSION) stays what the vendored
sqlite_store checks; a change to a part is a version bump of the part and a step (dbparts), not of that number.
"""
from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.contracts.dbparts import Part, Prune, doc_table
from taskloop.contracts.ledger import LedgerEntry
from taskloop.contracts.locks import EngineLock
from taskloop.contracts.requests import OwnerRequest
from taskloop.contracts.run import RunManifest
from taskloop.contracts.snapshots import Pin, ReflectState, ReleaseResult

REPORT_DOCS = "report_doc"  # the report stage's document: the reflect digest state
RELEASE_DOCS = "release_doc"  # the release stage's documents: the pin and the last release result

# The runs that may age out (the pipeline's rule; the history of other parts is pruned by it too). `?` is the cutoff; the temp table
# prune_keep_bead holds the beads the caller exempts.
ELIGIBLE = """SELECT r.run FROM run AS r
    WHERE r.ended < ? AND r.state NOT IN ('created','running')
    AND NOT EXISTS (SELECT 1 FROM temp.prune_keep_bead AS k WHERE k.bead=r.bead)
    AND NOT EXISTS (SELECT 1 FROM lease AS l WHERE l.run=r.run)
    AND NOT EXISTS (SELECT 1 FROM wait AS w WHERE w.run=r.run)
    AND NOT EXISTS (SELECT 1 FROM signal AS s WHERE s.run=r.run AND s.taken IS NULL)
    AND NOT EXISTS (SELECT 1 FROM ask AS a WHERE a.bead=r.bead AND a.status IN ('open','open_soft'))"""

DASH = Part(
    name="dash", version=1, tables=("source", "bead"),
    records=(Bead,),
    ddl="""
CREATE TABLE source (path TEXT PRIMARY KEY, family TEXT NOT NULL,
  dev INTEGER, ino INTEGER, size INTEGER, mtime_ns INTEGER, head TEXT,
  offset INTEGER NOT NULL DEFAULT 0, seen REAL NOT NULL, error TEXT);
CREATE TABLE bead (id TEXT PRIMARY KEY, repo_key TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  priority INTEGER, type TEXT NOT NULL DEFAULT '', parent TEXT NOT NULL DEFAULT '', assignee TEXT NOT NULL DEFAULT '',
  labels TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL, fetched REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0,
  body TEXT NOT NULL DEFAULT '{}');
CREATE INDEX bead_status ON bead(repo_key, status);
""")

PIPELINE = Part(
    name="pipeline", version=1, tables=("run", "attempt", "step", "effect", "wait", "checkpoint", "timed", "signal"),
    records=(RunManifest, Checkpoint, OwnerRequest),
    ddl="""
CREATE TABLE run (run TEXT PRIMARY KEY, repo TEXT NOT NULL, repo_key TEXT NOT NULL, bead TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT '', owner TEXT, session TEXT, loop TEXT, worktree TEXT, branch TEXT, sha TEXT,
  state TEXT NOT NULL, reason TEXT, started REAL NOT NULL, ended REAL, next_step TEXT,
  outcome TEXT, why TEXT, version TEXT, stats TEXT,
  bundle TEXT,
  facts TEXT, facts_upto INTEGER,
  manifest TEXT NOT NULL,
  rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX run_bead ON run(bead, started);
CREATE INDEX run_recent ON run(repo_key, started);
CREATE INDEX run_live ON run(state) WHERE state IN ('created','running');
CREATE TABLE attempt (run TEXT NOT NULL REFERENCES run, n INTEGER NOT NULL, host TEXT, pid INTEGER, start_id TEXT,
  started REAL NOT NULL, beat REAL, ended REAL, end_kind TEXT, fault_class TEXT, fingerprint TEXT, reason TEXT,
  PRIMARY KEY (run, n));
CREATE TABLE step (run TEXT NOT NULL REFERENCES run, key TEXT NOT NULL, try INTEGER NOT NULL, attempt INTEGER NOT NULL,
  status TEXT NOT NULL, started REAL NOT NULL, ended REAL, input_digest TEXT, result TEXT, fingerprint TEXT, calls INTEGER DEFAULT 0,
  PRIMARY KEY (run, key, try));
CREATE TABLE effect (
  key TEXT PRIMARY KEY,
  run TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL,
  intent_at REAL NOT NULL, done_at REAL, receipt TEXT
);
CREATE TABLE wait (
  id INTEGER PRIMARY KEY, repo TEXT NOT NULL, run TEXT, kind TEXT NOT NULL,
  wake_at REAL, wake_on TEXT, facts TEXT, since REAL NOT NULL, cleared REAL
);
CREATE TABLE checkpoint (bead TEXT PRIMARY KEY, t REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL);
CREATE TABLE timed (id INTEGER PRIMARY KEY, run TEXT NOT NULL, bead TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
  exec_s REAL NOT NULL, wait_s REAL NOT NULL, t REAL NOT NULL);
CREATE INDEX timed_run ON timed(run, id);
CREATE TABLE signal (
  id INTEGER PRIMARY KEY, run TEXT, kind TEXT NOT NULL,
  payload TEXT, at REAL NOT NULL, taken REAL
);
""",
    prune=(
        Prune("step", f"run IN ({ELIGIBLE})"),
        Prune("attempt", f"run IN ({ELIGIBLE})"),
        Prune("effect", f"run IN ({ELIGIBLE})"),
        Prune("timed", f"run IN ({ELIGIBLE})"),
        Prune("run", f"""run IN ({ELIGIBLE})
        AND NOT EXISTS (SELECT 1 FROM step WHERE step.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM attempt WHERE attempt.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM effect WHERE effect.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM timed WHERE timed.run=run.run)
        AND NOT EXISTS (SELECT 1 FROM check_round WHERE check_round.run=run.run)""",
              after=("step", "attempt", "effect", "timed", "check_round")),
    ))

SLOTS = Part(
    name="slots", version=1, tables=("lease",),
    records=(EngineLock,),
    ddl="""
CREATE TABLE lease (kind TEXT NOT NULL CHECK (kind IN ('run','loop','resource','slot')), name TEXT NOT NULL,
  holder TEXT NOT NULL, run TEXT, host TEXT, pid INTEGER, start_id TEXT, since REAL NOT NULL, beat REAL, until REAL,
  body TEXT, PRIMARY KEY (kind, name));
""")

ASKS = Part(
    name="asks", version=1, tables=("ask", "ask_ledger"),
    records=(Ask, LedgerEntry),
    ddl="""
CREATE TABLE ask (bead TEXT PRIMARY KEY, id TEXT NOT NULL, repo TEXT, status TEXT NOT NULL, t REAL NOT NULL, consumed REAL,
  body TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ask_live ON ask(status, t);
CREATE TABLE ask_ledger (id INTEGER PRIMARY KEY, t REAL NOT NULL, event TEXT NOT NULL, ask TEXT, bead TEXT, repo TEXT,
  body TEXT NOT NULL, origin TEXT NOT NULL UNIQUE);
""",
    prune=(Prune("ask_ledger", """t < ?
        AND NOT EXISTS (SELECT 1 FROM temp.prune_keep_bead AS k WHERE k.bead=ask_ledger.bead)
        AND NOT EXISTS (SELECT 1 FROM ask AS a JOIN temp.prune_keep_bead AS k ON k.bead=a.bead
            WHERE a.id=ask_ledger.ask)
        AND NOT EXISTS (SELECT 1 FROM ask AS a
            WHERE (a.id=ask_ledger.ask OR a.bead=ask_ledger.bead) AND a.status IN ('open','open_soft'))
        AND NOT EXISTS (SELECT 1 FROM run AS r
            WHERE r.bead=ask_ledger.bead AND r.state IN ('created','running'))"""),))

KV = Part(
    name="kv", version=1, tables=("kv",),
    records=(),
    ddl="""
CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, t REAL NOT NULL, stamp TEXT);
""")

RELEASE = Part(name="release", version=1, tables=(RELEASE_DOCS,), records=(Pin, ReleaseResult), ddl=doc_table(RELEASE_DOCS))

REPORT = Part(name="report", version=1, tables=(REPORT_DOCS,), records=(ReflectState,), ddl=doc_table(REPORT_DOCS))
