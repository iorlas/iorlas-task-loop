"""The step and round CLI tests' shared facts: the attempt key, the `rounds once` and `rounds start` argument lists, the moves a round
reports, and one admitted attempt in a factory.db file."""

import hashlib
from pathlib import Path

from doubles import pin_workflow
from sqlite_sidecar import transaction as begin_immediate
from sqlite_store import Store

from taskloop.attempt_types import AttemptKey
from taskloop.factory_schema import SCHEMA
from taskloop.operations import Move

KEY = AttemptKey("attempt", "dispatch-token-never-shown", 1)
NEXT = [
    "rounds",
    "once",
    "--backlog",
    "tasks",
    "--tracker-root",
    "/tracker",
    "--checkout",
    "/checkout",
    "--label",
    "auto",
    "--model",
    "m",
    "--effort",
    "high",
    "--minutes",
    "30",
]
MOVES = (
    Move("tl-3", "start", "started", "a3"),
    Move("tl-2", "report", "stuck:hung", "a2"),
    Move("tl-10", "skip", "abandoned"),
    Move("tl-4", "report", "failed:rejected:paths", "a4", "never shown"),
    Move("tl-5", "report", "claim_leaked"),
)
ROUNDS = ["rounds", "start", "--no-dashboard", *NEXT[2:]]


def admitted(path: Path) -> None:
    """One admitted, unregistered attempt (tasks/tl-1, deadline 100) and its reservation, as the conftest of tests/steps."""
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','s1','/slots/s1')")
        con.execute("INSERT INTO reservation VALUES ('s1','repo',1,'attempt')")
        pin_workflow(con)
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
            input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,engine_digest,workflow_digest,workflow_sha,admitted_at)
            VALUES ('attempt',?,1,'plan','beads','tasks','tl-1','/tracker','repo','s1','input.txt',?,1,'m','high',
            '{"harness":"codex","sandbox":"workspace-write"}',100,1,1,'dddddddddddddddddddddddddddddddddddddddd',
        'abababababababababababababababababababababababababababababababab',
        (SELECT digest FROM workflow_file),'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',1.0)""",
            (KEY.dispatch_token, hashlib.sha256(b"x").hexdigest()),
        )
    con.close()
