"""The one owner of factory.db DDL, its version and every column list of its tables.

v17: check-driven repeats retain their source checks link and start at the checked commit.
Drain old attempts before upgrading; refuse the old database, then discard only through its owning operation.

v11: `attempt.step` admits `implement`; `attempt.after_commit` names, for attempt 1 of every later step, the previous
step's published X it starts from. `setup_run` is the slot setup's record: "latest" is always the highest `run` of one
attempt, never a wall-clock order. v12 (tl-8bh9.14.6): the checks step's own tables, `checks_attempt` (one per run of the
profile's checks on a done implement attempt's X, numbered per implement attempt) and `check_result` (one check's result
in one block); `setup_run.attempt_id` names an `attempt` or a `checks_attempt`, so it has no foreign key. v13
(tl-8bh9.14.8): `land_candidate`, one squash S of a checked X onto origin's `main` at O with its validation, delivery and
close; `check_result.attempt_id` names a checks attempt or a land candidate, so it loses its foreign key. v14
(tl-8bh9.14.9): `attempt.label`, the approval label a round ingested the task under (NULL: started by hand), and
`task_hold`, a hold of a round-taken task's agent attempt with its tracker writes' phases (written only by `hold_store`).
v15 (tl-8bh9.14.134): `attempt.repeat_listing`, the JSON array of paths the failed verification listed (the unsafe path,
the leftovers, the ignored paths) that a repeat attempt answers; NULL for attempt 1. The dashboard shows it as the
verification's result. v16 (tl-8bh9.14.149): `attempt.harness` and `attempt.provider`, the agent harness the step ran under and the
provider of its model (`harness_choice`), shown on the dashboard. No migration: an older factory.db is refused (`schema`)."""

import sqlite3
from pathlib import Path

from sqlite_store import Schema, SchemaError

from taskloop.check_repeat.feedback import CheckRepeatReason
from taskloop.harness_choice import HarnessKind, Provider

_HARNESSES = ",".join(f"'{each}'" for each in HarnessKind)
_PROVIDERS = ",".join(f"'{each}'" for each in Provider)

SCHEMA = Schema(
    version=17,
    name="factory",
    steps={},
    ddl=f"""
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
 step TEXT NOT NULL CHECK(step IN ('plan','implement')),
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
 repeat_reason TEXT CHECK(repeat_reason IN ('uncommitted','unsafe','ignored','{CheckRepeatReason.FAILED_CHECK.value}')),
 source_checks_id TEXT UNIQUE REFERENCES checks_attempt(attempt_id),
 repeat_listing TEXT CHECK(repeat_listing IS NULL OR json_valid(repeat_listing)),
 after_commit TEXT CHECK(after_commit IS NULL OR length(after_commit) IN (40,64)),
 label TEXT CHECK(label IS NULL OR length(label) BETWEEN 1 AND 200),
 harness TEXT NOT NULL DEFAULT '{HarnessKind.CODEX}' CHECK(harness IN ({_HARNESSES})),
 provider TEXT NOT NULL DEFAULT '{Provider.OPENAI}' CHECK(provider IN ({_PROVIDERS})),
 CHECK((number = 1) = (previous_attempt_id IS NULL)), CHECK((number = 1) = (repeat_reason IS NULL)),
 CHECK(((number = 1 AND step <> 'plan') OR source_checks_id IS NOT NULL) = (after_commit IS NOT NULL)),
 CHECK((repeat_reason IS '{CheckRepeatReason.FAILED_CHECK.value}') = (source_checks_id IS NOT NULL)),
 CHECK(source_checks_id IS NULL OR step='implement'),
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
CREATE TABLE setup_run (
 attempt_id TEXT NOT NULL, run INTEGER NOT NULL CHECK(run >= 1),
 dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),
 digest TEXT NOT NULL CHECK(length(digest)=64),
 command INTEGER NOT NULL DEFAULT 0 CHECK(command >= 0),
 pid INTEGER, pgid INTEGER, proc_start TEXT, boot TEXT,
 started_at REAL NOT NULL, ended_at REAL, rc INTEGER,
 conclusion TEXT CHECK(conclusion IN ('passed','failed','timed_out','lingering','dirty','interrupted')),
 CHECK((ended_at IS NULL) = (conclusion IS NULL)), PRIMARY KEY (attempt_id, run)
);
CREATE TABLE checks_attempt (
 attempt_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 after_attempt_id TEXT NOT NULL REFERENCES attempt(attempt_id),
 number INTEGER NOT NULL CHECK(number >= 1),
 slot TEXT NOT NULL,
 slot_head TEXT NOT NULL CHECK(length(slot_head) IN (40,64)),
 target_commit TEXT NOT NULL CHECK(length(target_commit) IN (40,64)),
 target_seen TEXT CHECK(target_seen IS NULL OR length(target_seen) IN (40,64)),
 required TEXT NOT NULL,
 profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),
 deadline REAL NOT NULL, entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 phase TEXT NOT NULL DEFAULT 'admitted' CHECK(phase IN ('admitted','concluded')),
 rev INTEGER NOT NULL DEFAULT 0,
 refusal TEXT, refusals INTEGER NOT NULL DEFAULT 0 CHECK(refusals >= 0),
 conclusion TEXT CHECK(conclusion IN ('passed','failed')), reason TEXT, concluded_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 abandoned INTEGER NOT NULL DEFAULT 0 CHECK(abandoned IN (0,1)),
 CHECK((phase='concluded') = (conclusion IS NOT NULL)), CHECK((conclusion IS NULL) = (concluded_at IS NULL)),
 CHECK((conclusion='failed') = (reason IS NOT NULL)), CHECK((released_at IS NULL) = (parked IS NULL)),
 CHECK(abandoned=0 OR released_at IS NOT NULL), CHECK(abandoned=1 OR released_at IS NULL OR phase='concluded'),
 CHECK((refusal IS NULL) = (refusals = 0)),
 CHECK((entry_pid IS NULL) = (entry_start IS NULL) AND (entry_pid IS NULL) = (entry_boot IS NULL)),
 UNIQUE (after_attempt_id, number)
);
CREATE TABLE check_result (
 attempt_id TEXT NOT NULL, block INTEGER NOT NULL CHECK(block >= 1),
 position INTEGER NOT NULL CHECK(position >= 0),
 name TEXT NOT NULL, dispatch_token TEXT NOT NULL, generation INTEGER NOT NULL,
 argv_digest TEXT CHECK(argv_digest IS NULL OR length(argv_digest)=64), timeout INTEGER CHECK(timeout IS NULL OR timeout >= 1),
 pid INTEGER, pgid INTEGER, proc_start TEXT, boot TEXT,
 started_at REAL NOT NULL, ended_at REAL, rc INTEGER,
 conclusion TEXT CHECK(conclusion IN ('passed','failed','timed_out','lingering','dirty','undefined','interrupted')),
 CHECK((ended_at IS NULL) = (conclusion IS NULL)), CHECK((argv_digest IS NULL) = (conclusion IS 'undefined')),
 CHECK((timeout IS NULL) = (argv_digest IS NULL)),
 CHECK((pid IS NULL) = (pgid IS NULL) AND (pid IS NULL) = (proc_start IS NULL) AND (pid IS NULL) = (boot IS NULL)),
 CHECK(conclusion IS NOT 'undefined' OR (pid IS NULL AND rc IS NULL)), CHECK(rc IS NULL OR conclusion IS NOT NULL),
 PRIMARY KEY (attempt_id, block, position), UNIQUE (attempt_id, block, name)
);
CREATE TABLE land_candidate (
 candidate_id TEXT PRIMARY KEY, dispatch_token TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL,
 checks_attempt_id TEXT NOT NULL REFERENCES checks_attempt(attempt_id),
 number INTEGER NOT NULL CHECK(number >= 1),
 origin_commit TEXT NOT NULL CHECK(length(origin_commit) IN (40,64)),
 commit_sha TEXT NOT NULL CHECK(length(commit_sha) IN (40,64)),
 tree_same INTEGER NOT NULL CHECK(tree_same IN (0,1)),
 required TEXT NOT NULL,
 slot TEXT, slot_head TEXT CHECK(slot_head IS NULL OR length(slot_head) IN (40,64)),
 deadline REAL, profile_digest TEXT CHECK(profile_digest IS NULL OR length(profile_digest)=64),
 entry_pid INTEGER, entry_start TEXT, entry_boot TEXT,
 validation TEXT CHECK(validation IS NULL OR validation IN ('same_tree','no_change','passed','failed')),
 reason TEXT, validated_at REAL,
 released_at REAL, parked TEXT CHECK(parked IS NULL OR length(parked) IN (40,64)),
 superseded TEXT CHECK(superseded IS NULL OR superseded IN ('moved','withdrawn','gone','abandoned')), superseded_at REAL,
 delivery TEXT CHECK(delivery IS NULL OR delivery IN ('pushed','no_change')), delivered_at REAL,
 remote_head TEXT CHECK(remote_head IS NULL OR length(remote_head) IN (40,64)),
 close TEXT CHECK(close IS NULL OR close IN ('closed','already_closed')), closed_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((slot IS NULL) = (slot_head IS NULL) AND (slot IS NULL) = (deadline IS NULL)),
 CHECK((slot IS NULL) = (validation IS NOT NULL AND validation IN ('same_tree','no_change'))),
 CHECK((validation IS 'no_change') = (delivery IS 'no_change')),
 CHECK((validation IS NULL) = (validated_at IS NULL)), CHECK((validation IS 'failed') = (reason IS NOT NULL)),
 CHECK((entry_pid IS NULL) = (entry_start IS NULL) AND (entry_pid IS NULL) = (entry_boot IS NULL)),
 CHECK(entry_pid IS NULL OR slot IS NOT NULL),
 CHECK((released_at IS NULL) = (parked IS NULL)), CHECK(released_at IS NULL OR slot IS NOT NULL),
 CHECK((superseded IS NULL) = (superseded_at IS NULL)), CHECK(superseded IS NULL OR delivery IS NULL),
 CHECK((delivery IS NULL) = (delivered_at IS NULL)), CHECK((delivery IS 'pushed') = (remote_head IS NOT NULL)),
 CHECK(delivery IS NULL OR (validation IS NOT NULL AND validation IN ('same_tree','no_change','passed'))),
 CHECK((close IS NULL) = (closed_at IS NULL)), CHECK(close IS NULL OR delivery IS NOT NULL),
 UNIQUE (checks_attempt_id, number)
);
CREATE UNIQUE INDEX land_delivered ON land_candidate(checks_attempt_id) WHERE delivery IS NOT NULL;
CREATE TABLE task_hold (
 attempt_id TEXT PRIMARY KEY REFERENCES attempt(attempt_id),
 cause_id TEXT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 200),
 held_at REAL NOT NULL,
 labels TEXT CHECK(labels IS NULL OR labels IN ('moved','absent','not_ours','closed','missing','superseded')),
 labelled_at REAL,
 commenting_at REAL, commented_at REAL,
 cleared_at REAL,
 rev INTEGER NOT NULL DEFAULT 0,
 CHECK((labels IS NULL) = (labelled_at IS NULL)),
 CHECK(commented_at IS NULL OR commenting_at IS NOT NULL),
 CHECK(commented_at IS NULL OR (labels IS NOT NULL AND labels IN ('moved','absent','not_ours'))),
 CHECK(cleared_at IS NULL OR labels IS NOT NULL)
);
""",
)

SLOT = "repo_id,name,path"
RESERVATION = "slot,repo_id,generation,attempt_id"
ATTEMPT_ADMITTED = (
    "attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,"
    "schema_version,model,effort,sandbox,deadline,number,previous_attempt_id,repeat_reason,repeat_listing,seq,slot_head,after_commit,label,harness,provider,source_checks_id"
)
ATTEMPT_LOADED = (
    "backlog,task_id,repo_id,slot,input_path,input_digest,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,"
    "phase,rev,worker_pid,worker_pgid,worker_start,worker_boot,session_ref,session_conflict,base_commit,end_commit,"
    "number,previous_attempt_id,step,after_commit,harness,source_checks_id"
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
CHECKS_ADMITTED = "attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,required,deadline"
CHECKS_LOADED = (
    "attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,target_seen,required,"
    "profile_digest,deadline,entry_pid,entry_start,entry_boot,phase,rev,refusal,refusals,conclusion,reason,concluded_at,"
    "released_at,parked,abandoned"
)
LAND_ADMITTED = (
    "candidate_id,dispatch_token,generation,checks_attempt_id,number,origin_commit,commit_sha,tree_same,required,slot,slot_head,"
    "deadline,validation,validated_at,delivery,delivered_at"
)
LAND_LOADED = (
    "candidate_id,dispatch_token,generation,checks_attempt_id,number,origin_commit,commit_sha,tree_same,required,slot,slot_head,"
    "deadline,profile_digest,entry_pid,entry_start,entry_boot,validation,reason,validated_at,released_at,parked,superseded,"
    "superseded_at,delivery,delivered_at,remote_head,close,closed_at,rev"
)
HOLD = "attempt_id,cause_id,reason,held_at,labels,labelled_at,commenting_at,commented_at,cleared_at,rev"
CHECK_RESULT = "block,position,name,argv_digest,timeout,pid,pgid,proc_start,boot,started_at,ended_at,rc,conclusion"


# A repeat of attempt `p` exists (`previous_attempt_id` links only a step's repeats): its chain is frozen.
REPEATED = "EXISTS (SELECT 1 FROM attempt s WHERE s.previous_attempt_id=p.attempt_id)"
# A later attempt of the same task exists (a repeat, the next step or a fresh start): attempt `p` is no longer the current
# one. The one "not current" rule of every read and fence; `previous_attempt_id` links only a step's repeats.
LATER = """EXISTS (SELECT 1 FROM attempt later WHERE later.adapter=p.adapter AND later.backlog=p.backlog
AND later.task_id=p.task_id AND later.seq>p.seq)"""
# The release's "not current" rule (`slot_release` ROW, FENCE, FLIP): `LATER`, or the attempt's latest checks attempt (its
# highest `number`) is not abandoned, so the claim is that checks attempt's now and the task's abandon goes checks first.
LATEST_CHECKS = """c.after_attempt_id=p.attempt_id AND c.abandoned=0
AND c.number=(SELECT max(d.number) FROM checks_attempt d WHERE d.after_attempt_id=p.attempt_id)"""  # `c`: p's live checks attempt
SUCCESSOR = f"({LATER} OR EXISTS (SELECT 1 FROM checks_attempt c WHERE {LATEST_CHECKS}))"

# A land candidate's validation writes (`land_store.HELD`, and its half of `check_store.RESULT_HELD`): the candidate
# pending (no validation yet, not superseded) and holding its reservation at the key's generation (`CANDIDATE_RESERVED`).
# Bound with its key.
CANDIDATE_RESERVED = """FROM land_candidate l JOIN checks_attempt k ON k.attempt_id=l.checks_attempt_id
JOIN attempt i ON i.attempt_id=k.after_attempt_id
JOIN reservation q ON q.repo_id=i.repo_id AND q.slot=l.slot AND q.attempt_id=l.candidate_id AND q.generation=l.generation
WHERE l.candidate_id=? AND l.dispatch_token=? AND l.generation=?"""
CANDIDATE_HELD = "SELECT 1 " + CANDIDATE_RESERVED + " AND l.validation IS NULL AND l.superseded IS NULL"
# The candidates of checks attempt `c`'s task: those of every checks attempt of its implement attempt (a re-run of the
# checks never hides a delivered or pushable candidate of an earlier one).
OF_TASK = "l.checks_attempt_id IN (SELECT e.attempt_id FROM checks_attempt e WHERE e.after_attempt_id=c.after_attempt_id)"
# A candidate of `c`'s implement attempt is delivered: its code is on origin's `main` (the word `landed`).
LANDED = "EXISTS (SELECT 1 FROM land_candidate l WHERE " + OF_TASK + " AND l.delivery IS NOT NULL)"
# ... and the task is closed in the tracker by it (`close` implies `delivery`): nothing is left to finish.
CLOSED = "EXISTS (SELECT 1 FROM land_candidate l WHERE " + OF_TASK + " AND l.close IS NOT NULL)"
# The abandon, re-run and insert fence of checks attempt `c`: a candidate of its implement attempt is delivered, holds its
# slot, or is pushable (validated `same_tree` or `passed`, not superseded: S may already be on origin). Words `landed`,
# else `landing`.
LANDING = "EXISTS (SELECT 1 FROM land_candidate l WHERE " + OF_TASK + """ AND (l.delivery IS NOT NULL
OR (l.slot IS NOT NULL AND l.released_at IS NULL)
OR (l.superseded IS NULL AND l.validation IS NOT NULL AND l.validation IN ('same_tree','passed'))))"""


def marks(columns: str) -> str:
    """One `?` per column of a column list."""
    return ",".join("?" * len(columns.split(",")))


def prefixed(alias: str, columns: str) -> str:
    return ",".join(f"{alias}.{column}" for column in columns.split(","))


def current(con: sqlite3.Connection) -> bool:
    """The connection's database is exactly this code's schema version."""
    return con.execute("PRAGMA user_version").fetchone() == (SCHEMA.version,)


def refusal(error: SchemaError, path: Path) -> str:
    """The words of `refused schema`: the store's for a newer file (this code must be updated); for an older one, which
    nothing upgrades (`SCHEMA.steps` is empty), the truth that an older version wrote it and that the owner discards it."""
    found = _recorded(path)
    if found is None or found >= SCHEMA.version:
        return str(error)
    if found == 0:
        return (f"factory.db records no schema version, this code knows v{SCHEMA.version}: it is not a factory.db; the "
                "owner moves it aside, then tl slot adopt")
    return (f"factory is schema v{found}, this code knows v{SCHEMA.version}: an older version wrote it and nothing upgrades "
            "it; the owner discards factory.db (moves it aside), then tl slot adopt")


def _recorded(path: Path) -> int | None:
    """The schema version the file records, read-only (only to word a refusal); None when it cannot be read."""
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, OSError, ValueError):
        return None
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        con.close()
