"""The one owner of factory.db DDL, its version and every column list of its tables."""

import sqlite3

from sqlite_store import Schema

SCHEMA = Schema(
    version=10,
    name="factory",
    steps={},
    ddl="""
CREATE TABLE slot (
 repo_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
 PRIMARY KEY (repo_id, name)
);
CREATE TABLE reservation (
 slot TEXT NOT NULL, repo_id TEXT NOT NULL, generation INTEGER NOT NULL, attempt_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY (repo_id, slot)
);
CREATE TABLE attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 step TEXT NOT NULL CHECK(step IN ('plan')),
 adapter TEXT NOT NULL CHECK(adapter='beads'), backlog TEXT NOT NULL, task_id TEXT NOT NULL,
 tracker_root TEXT NOT NULL CHECK(substr(tracker_root,1,1)='/'),
 repo_id TEXT NOT NULL, slot TEXT NOT NULL, input_path TEXT NOT NULL, input_digest TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version=1), model TEXT NOT NULL, effort TEXT NOT NULL,
 sandbox TEXT NOT NULL, deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','dispatching','registered','captured')),
 rev INTEGER NOT NULL DEFAULT 0, worker_pid INTEGER, worker_pgid INTEGER, worker_start TEXT, worker_boot TEXT,
 session_ref TEXT, session_conflict INTEGER NOT NULL DEFAULT 0 CHECK(session_conflict IN (0,1)),
 base_commit TEXT CHECK(base_commit IS NULL OR length(base_commit) IN (40,64)),
 end_commit TEXT CHECK(end_commit IS NULL OR length(end_commit) IN (40,64)),
 number INTEGER NOT NULL CHECK(number >= 1), seq INTEGER NOT NULL CHECK(seq >= 1),
 slot_head TEXT NOT NULL CHECK(length(slot_head) IN (40,64)),
 previous_attempt_id TEXT UNIQUE REFERENCES attempt(attempt_id),
 repeat_reason TEXT CHECK(repeat_reason IN ('uncommitted','unsafe','ignored')),
 CHECK((number = 1) = (previous_attempt_id IS NULL)), CHECK((number = 1) = (repeat_reason IS NULL)),
 CHECK(phase='admitted' OR base_commit IS NOT NULL), CHECK(end_commit IS NULL OR phase='captured'),
 UNIQUE(adapter, backlog, task_id, seq)
);
CREATE TABLE execution (
 attempt_id TEXT PRIMARY KEY REFERENCES attempt(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 rc INTEGER, timed_out INTEGER NOT NULL, stop TEXT, watch TEXT, work INTEGER NOT NULL, stands INTEGER NOT NULL,
 answered INTEGER, reason TEXT, http_status INTEGER, t_in INTEGER, t_cached INTEGER, t_out INTEGER,
 c_in INTEGER, c_cached INTEGER, c_out INTEGER, turns INTEGER, session TEXT,
 stdout_path TEXT NOT NULL, stdout_digest TEXT NOT NULL, stderr_path TEXT NOT NULL, stderr_digest TEXT NOT NULL,
 answer_path TEXT NOT NULL, answer_digest TEXT NOT NULL, diagnostic_path TEXT NOT NULL, diagnostic_digest TEXT NOT NULL,
 answer_kind TEXT NOT NULL DEFAULT 'validation_pending'
  CHECK(answer_kind IN ('validation_pending','valid','missing','json_invalid','schema_invalid')),
 disposition TEXT, effect TEXT CHECK(effect IN ('commit','keep','none')), commit_paths TEXT, commit_message TEXT,
 session_state TEXT NOT NULL CHECK(session_state IN ('complete','pending','conflict','fault'))
);
CREATE TABLE verification (
 attempt_id TEXT PRIMARY KEY REFERENCES execution(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 verdict TEXT NOT NULL CHECK(verdict IN ('verified','rejected')), reason TEXT, blob TEXT, observed_at REAL NOT NULL,
 reused INTEGER NOT NULL DEFAULT 0 CHECK(reused IN (0,1)), CHECK(reused=0 OR verdict='verified'),
 CHECK((verdict='verified') = (reason IS NULL))
);
CREATE TABLE slot_release (
 attempt_id TEXT PRIMARY KEY REFERENCES attempt(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 head TEXT NOT NULL CHECK(length(head) IN (40,64)), released_at REAL NOT NULL,
 claim TEXT NOT NULL CHECK(claim IN ('kept','unclaiming','unclaimed','not_held'))
);
CREATE TABLE published_branch (
 attempt_id TEXT PRIMARY KEY REFERENCES verification(attempt_id), dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),
 remote_head TEXT NOT NULL CHECK(length(remote_head) IN (40,64)),
 published_at REAL NOT NULL
);
""",
)

SLOT = "repo_id,name,path"
RESERVATION = "slot,repo_id,generation,attempt_id"
ATTEMPT_ADMITTED = (
    "attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,"
    "schema_version,model,effort,sandbox,deadline,number,previous_attempt_id,repeat_reason,seq,slot_head"
)
ATTEMPT_LOADED = (
    "backlog,task_id,repo_id,slot,input_path,input_digest,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,"
    "phase,rev,worker_pid,worker_pgid,worker_start,worker_boot,session_ref,session_conflict,base_commit,end_commit,"
    "number,previous_attempt_id,step"
)
FACTS = (
    "rc,timed_out,stop,watch,work,stands,answered,reason,http_status,t_in,t_cached,t_out,"
    "c_in,c_cached,c_out,turns,session"
)
EVIDENCE = "stdout_path,stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest"
ANSWER = "answer_kind,disposition,effect,commit_paths,commit_message,session_state"
VERDICT = "verdict,reason,blob,reused"
RELEASE = "attempt_id,dispatch_token,generation,head,released_at,claim"
PUBLISHED = "attempt_id,dispatch_token,generation,commit_sha,remote_head,published_at"  # X pushed; the remote tip confirmed


def marks(columns: str) -> str:
    """One `?` per column of a column list."""
    return ",".join("?" * len(columns.split(",")))


def prefixed(alias: str, columns: str) -> str:
    return ",".join(f"{alias}.{column}" for column in columns.split(","))


def current(con: sqlite3.Connection) -> bool:
    """The connection's database is exactly this code's schema version."""
    return con.execute("PRAGMA user_version").fetchone() == (SCHEMA.version,)
