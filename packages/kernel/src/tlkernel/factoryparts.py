"""factory.db as the parts that own its tables (stage-isolation 3.1): today's schema declared at version 1, each part by its future owner.

The tables stay here until their stage's own store module defines them (the D-* beads of ARCHVERT); every table is in exactly one part.
The frozen `user_version` (factorydb.SCHEMA_VERSION) stays what the vendored sqlite_store checks; a change to a part is a version bump
of the part and a step (dbparts), not of that number.
"""
import sqlite3
from typing import Final

from tlkernel import factoryretired
from tlkernel.ask import Ask
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint, CursorBody, LandSection, LookSection, PlanSection, WriteSection
from tlkernel.checks import Durations
from tlkernel.dbparts import Part, Prune, doc_table
from tlkernel.docrows import (
    BEADCACHE_DOCS,
    CHECKPOINT_SECTIONS,
    DISK_DOCS,
    DURATION_DOCS,
    FLAKE_DOCS,
    INDEX_DOCS,
    LANES_DOCS,
    LOOK_DOCS,
    LOOP_DOCS,
    QUEUE_DOCS,
    RECEIPT_DOCS,
    RELEASE_DOCS,
    REPORT_DOCS,
    REPOS_DOCS,
    RUN_DOCS,
    TICKET_DOCS,
    WORK_DOCS,
    WORKTREE_DOCS,
)
from tlkernel.flakes import FlakeLog
from tlkernel.ledger import Adr, LedgerEntry
from tlkernel.loop import BadVersions, LoopCommand, Rest
from tlkernel.parks import Park
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.requests import OwnerRequest
from tlkernel.review import ReviewState
from tlkernel.run import HandoffMirror, RunCounters, RunManifest
from tlkernel.rundocs import PrepareStamp
from tlkernel.snapshots import Pin, ReflectState, ReleaseResult, ReposIndex, SharedNotes, StatusSnapshot, StatusTried
from tlkernel.worktrees import Owned

# Parts that existed once; a rw launch deletes their schema_part row and drops their tables; D-KV.
DROPPED_PARTS: Final = factoryretired.DROPPED_PARTS

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

def close_intent(con: sqlite3.Connection) -> None:
    """pipeline v1 -> v2: checkpoint v4 keeps CloseIntent; old bodies stay foreign and are refused by their reader."""


SECTION_DDL = (f"CREATE TABLE {CHECKPOINT_SECTIONS} (bead TEXT NOT NULL, section TEXT NOT NULL, "
               "body TEXT NOT NULL, PRIMARY KEY (bead, section))")


def checkpoint_sections(con: sqlite3.Connection) -> None:
    """pipeline v2 -> v3: add section storage; old checkpoint bodies remain foreign."""
    con.execute(SECTION_DDL)


PIPELINE = Part(
    name="pipeline", version=3,
    tables=("run", "attempt", "step", "effect", "wait", "checkpoint", CHECKPOINT_SECTIONS, "timed", "signal"),
    records=(RunManifest, Checkpoint, CursorBody, PlanSection, WriteSection, LandSection, LookSection, ReviewState, OwnerRequest),
    steps={1: close_intent, 2: checkpoint_sections},
    ddl=f"""
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
{SECTION_DDL};
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

PARK_DDL = "CREATE TABLE park (bead TEXT PRIMARY KEY, t REAL NOT NULL, body TEXT NOT NULL)"



def add_park(con: sqlite3.Connection) -> None:
    """asks v1 -> v2: parks leave the pipeline's `wait` table (no rows carried over)."""
    con.execute(PARK_DDL)


ASKS = Part(
    name="asks", version=2, tables=("ask", "ask_ledger", "park"),
    records=(Ask, LedgerEntry, Park),
    steps={1: add_park},
    ddl=f"""
CREATE TABLE ask (bead TEXT PRIMARY KEY, id TEXT NOT NULL, repo TEXT, status TEXT NOT NULL, t REAL NOT NULL, consumed REAL,
  body TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0);
CREATE INDEX ask_live ON ask(status, t);
{PARK_DDL};
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


def discard_old_pin(con: sqlite3.Connection) -> None:
    """release v1 -> v2: discard the retired two-plugin pin."""
    con.execute(f"DELETE FROM {RELEASE_DOCS} WHERE k='pin'")


RELEASE = Part(name="release", version=2, tables=(RELEASE_DOCS,), records=(Pin, ReleaseResult),
               ddl=doc_table(RELEASE_DOCS), steps={1: discard_old_pin})

REPORT = Part(name="report", version=1, tables=(REPORT_DOCS,), records=(ReflectState,), ddl=doc_table(REPORT_DOCS))

WORK = Part(name="work", version=1, tables=(WORK_DOCS,), records=(Adr,), ddl=doc_table(WORK_DOCS))


def loop_bad_versions(con: sqlite3.Connection) -> None:
    """loop v1 -> v2: the BadVersions record joined the part; no stored row changes."""


LOOP = Part(name="loop", version=2, tables=(LOOP_DOCS,), records=(LoopCommand, Rest, BadVersions), ddl=doc_table(LOOP_DOCS),
            steps={1: loop_bad_versions})
LOOK = Part(name="look", version=1, tables=(LOOK_DOCS,), records=(), ddl=doc_table(LOOK_DOCS))


def lanes_shared_notes(con: sqlite3.Connection) -> None:
    """lanes v1 -> v2: the SharedNotes record joined the part; no stored row changes."""


LANES = Part(name="lanes", version=2, tables=(LANES_DOCS,), records=(StatusSnapshot, StatusTried, SharedNotes),
             ddl=doc_table(LANES_DOCS), steps={1: lanes_shared_notes})

RECEIPT = Part(name="receipt", version=1, tables=(RECEIPT_DOCS,), records=(), ddl=doc_table(RECEIPT_DOCS))
BEADCACHE = Part(name="beadcache", version=1, tables=(BEADCACHE_DOCS,), records=(), ddl=doc_table(BEADCACHE_DOCS))
REPOS = Part(name="repos", version=1, tables=(REPOS_DOCS,), records=(ReposIndex,), ddl=doc_table(REPOS_DOCS))
TICKET = Part(name="ticket", version=1, tables=(TICKET_DOCS,), records=(), ddl=doc_table(TICKET_DOCS))
INDEX = Part(name="index", version=1, tables=(INDEX_DOCS,), records=(), ddl=doc_table(INDEX_DOCS))
WORKTREE = Part(name="worktree", version=1, tables=(WORKTREE_DOCS,), records=(Owned,), ddl=doc_table(WORKTREE_DOCS))
DISK = Part(name="disk", version=1, tables=(DISK_DOCS,), records=(), ddl=doc_table(DISK_DOCS))

QUEUE = Part(name="queue", version=1, tables=(QUEUE_DOCS,), records=(QueueDoc, QueueState), ddl=doc_table(QUEUE_DOCS))
FLAKE = Part(name="flake", version=1, tables=(FLAKE_DOCS,), records=(FlakeLog,), ddl=doc_table(FLAKE_DOCS))
RUNDOC = Part(name="rundoc", version=1, tables=(RUN_DOCS,), records=(RunCounters, HandoffMirror, PrepareStamp),
              ddl=doc_table(RUN_DOCS))
DURATION = Part(name="duration", version=1, tables=(DURATION_DOCS,), records=(Durations,), ddl=doc_table(DURATION_DOCS))
