"""The one owner of factory.db DDL, its version and every column list of its tables."""

import sqlite3

from sqlite_store import Schema

SCHEMA = Schema(
    version=4,
    name="factory",
    steps={},
    ddl="""
CREATE TABLE slot (
 repo_id TEXT NOT NULL, name TEXT NOT NULL, cwd TEXT NOT NULL,
 PRIMARY KEY (repo_id, name)
);
CREATE TABLE reservation (
 slot TEXT NOT NULL, repo_id TEXT NOT NULL, cwd TEXT NOT NULL,
 generation INTEGER NOT NULL, attempt_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY (repo_id, slot)
);
CREATE TABLE plan_attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 adapter TEXT NOT NULL CHECK(adapter='beads'), backlog TEXT NOT NULL, task_id TEXT NOT NULL,
 repo_id TEXT NOT NULL, slot TEXT NOT NULL, input_path TEXT NOT NULL, input_digest TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version=1), model TEXT NOT NULL, effort TEXT NOT NULL,
 sandbox TEXT NOT NULL, deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','dispatching','registered','captured')),
 rev INTEGER NOT NULL DEFAULT 0, worker_pid INTEGER, worker_pgid INTEGER, worker_start TEXT, worker_boot TEXT,
 session_ref TEXT, session_conflict INTEGER NOT NULL DEFAULT 0 CHECK(session_conflict IN (0,1)),
 base_commit TEXT CHECK(base_commit IS NULL OR length(base_commit) IN (40,64)),
 plan_commit TEXT CHECK(plan_commit IS NULL OR length(plan_commit) IN (40,64)),
 CHECK(phase='admitted' OR base_commit IS NOT NULL), CHECK(plan_commit IS NULL OR phase='captured'),
 UNIQUE(adapter, backlog, task_id)
);
CREATE TABLE plan_execution (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_attempt(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 rc INTEGER, timed_out INTEGER NOT NULL, stop TEXT, watch TEXT, work INTEGER NOT NULL, stands INTEGER NOT NULL,
 answered INTEGER, reason TEXT, http_status INTEGER, tokens_known INTEGER NOT NULL, t_in INTEGER, t_cached INTEGER, t_out INTEGER,
 cumulative_known INTEGER NOT NULL, c_in INTEGER, c_cached INTEGER, c_out INTEGER, turns INTEGER, session TEXT,
 stdout_path TEXT NOT NULL, stdout_digest TEXT NOT NULL, stderr_path TEXT NOT NULL, stderr_digest TEXT NOT NULL,
 answer_path TEXT NOT NULL, answer_digest TEXT NOT NULL, diagnostic_path TEXT NOT NULL, diagnostic_digest TEXT NOT NULL,
 answer_kind TEXT NOT NULL DEFAULT 'validation_pending'
  CHECK(answer_kind IN ('validation_pending','valid','missing','json_invalid','schema_invalid')),
 disposition TEXT, plan_path TEXT, commit_paths TEXT, commit_message TEXT,
 publication TEXT NOT NULL CHECK(publication IN ('complete','pending','conflict','fault'))
);
CREATE TABLE plan_verification (
 attempt_id TEXT PRIMARY KEY REFERENCES plan_execution(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 verdict TEXT NOT NULL CHECK(verdict IN ('verified','rejected')), reason TEXT, plan_blob TEXT, observed_at REAL NOT NULL,
 reused INTEGER NOT NULL DEFAULT 0 CHECK(reused IN (0,1)), CHECK(reused=0 OR verdict='verified'),
 CHECK((verdict='verified') = (reason IS NULL)), CHECK((verdict='verified') = (plan_blob IS NOT NULL))
);
""",
)

SLOT = "repo_id,name,cwd"
RESERVATION = "slot,repo_id,cwd,generation,attempt_id"
ATTEMPT_ADMITTED = (
    "attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,"
    "schema_version,model,effort,sandbox,deadline"
)
ATTEMPT_LOADED = (
    "backlog,task_id,repo_id,slot,input_path,input_digest,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,"
    "phase,rev,worker_pid,worker_pgid,worker_start,worker_boot,session_ref,session_conflict,base_commit,plan_commit"
)
FACTS = (
    "rc,timed_out,stop,watch,work,stands,answered,reason,http_status,tokens_known,t_in,t_cached,t_out,"
    "cumulative_known,c_in,c_cached,c_out,turns,session"
)
EVIDENCE = "stdout_path,stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest"
ANSWER = "answer_kind,disposition,plan_path,commit_paths,commit_message,publication"
VERDICT = "verdict,reason,plan_blob,reused"


def marks(columns: str) -> str:
    """One `?` per column of a column list."""
    return ",".join("?" * len(columns.split(",")))


def prefixed(alias: str, columns: str) -> str:
    return ",".join(f"{alias}.{column}" for column in columns.split(","))


def current(con: sqlite3.Connection) -> bool:
    """The connection's database is exactly this code's schema version."""
    return con.execute("PRAGMA user_version").fetchone() == (SCHEMA.version,)
