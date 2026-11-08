"""The registry: every TL_* and TASK_LOOP_* name the engine exports, hands over or reads. The code, SKILL.md,
the docs and the prompts say it by this table (tests/rules/test_envvars.py holds the three equal)."""
from enum import StrEnum
from typing import Final


class EnvVar(StrEnum):
    # exported into every command of a bead / check
    TL_SLOT = "TL_SLOT"                          # the slot's name (domain/slot_env)
    TL_ARTIFACT_DIR = "TL_ARTIFACT_DIR"          # <run dir>/attempts/<run>-attempt-R/artifacts/<step>/attempt-N: where an attempt writes
    TL_ARTIFACT_STEP = "TL_ARTIFACT_STEP"        # the id of the check that is running
    TL_RUN_ID = "TL_RUN_ID"                      # the id of the run a command belongs to (the run_id of its rows)
    TL_RUN_DIR = "TL_RUN_DIR"                    # the run's folder
    TL_ATTEMPT = "TL_ATTEMPT"                    # N of this attempt (the N of TL_ARTIFACT_DIR)
    TL_WORKTREE = "TL_WORKTREE"                  # the worktree the run works in
    TL_BRANCH = "TL_BRANCH"                      # the branch checked out in it
    TL_WORKER_MB = "TL_WORKER_MB"                # address-space cap of each xdist worker (dev/runtests.py)
    TL_GREEN_LEDGER = "TL_GREEN_LEDGER"          # 1: dev/runtests.py skips test files green on their key (the land gate sets it)
    TL_SCRATCH = "TL_SCRATCH"                    # moves the scratch root (contracts/scratch.py; dev/runtests.py reads it too)
    # handovers between two processes of the engine (one typed record each, see contracts/env.py)
    TL_REEXEC = "TL_REEXEC"                      # the run that re-execs itself after a code update
    TL_LOOP_STATE = "TL_LOOP_STATE"              # the loop's state across its exec
    TL_RELEASE_REEXEC = "TL_RELEASE_REEXEC"      # set in the exec'd release: it never execs again
    TL_JUDGE_TL = "TL_JUDGE_TL"                  # the tl.py of the child's own install: judges its pushes
    TASK_LOOP_SLOT_BEAD = "TASK_LOOP_SLOT_BEAD"  # the bead whose slot this process holds
    TASK_LOOP_ACTOR = "TASK_LOOP_ACTOR"          # the loop's actor name, inherited by its run-tasks
    TASK_LOOP_SESSION = "TASK_LOOP_SESSION"      # the engine's or loop's session id
    TASK_LOOP_LOOP_ID = "TASK_LOOP_LOOP_ID"      # the opaque id of the loop lifetime a run-task belongs to (kept across the loop's exec)
    TASK_LOOP_LOOP_PID = "TASK_LOOP_LOOP_PID"    # the pid of the loop a run-task belongs to
    TASK_LOOP_RUN_LOG = "TASK_LOOP_RUN_LOG"      # the parent's console log, projected at the run's finish
    TASK_LOOP_SLOT = "TASK_LOOP_SLOT"            # the parent's slot name for the loop history
    TASK_LOOP_WORKER = "TASK_LOOP_WORKER"        # set to 1 in a worker's environment
    # settings the owner may set
    TASK_LOOP_DASH_BIND = "TASK_LOOP_DASH_BIND"
    TASK_LOOP_DASH_PORT = "TASK_LOOP_DASH_PORT"
    TASK_LOOP_DASH_DEV_PUBLIC = "TASK_LOOP_DASH_DEV_PUBLIC"
    TASK_LOOP_DASH_IDLE_H = "TASK_LOOP_DASH_IDLE_H"


# Families: a name made of a prefix and a check id (domain/checks/names.py builds them; a check reads an earlier one's log and exit code).
CHECK_LOG_PREFIX: Final = "TL_CHECK_LOG_"
CHECK_RC_PREFIX: Final = "TL_CHECK_RC_"
PREFIXES: Final = (CHECK_LOG_PREFIX, CHECK_RC_PREFIX)
# Stable names for repositories whose commands task-loop runs.
CONSUMER: Final = (
    (EnvVar.TL_ARTIFACT_DIR.value, "Where this attempt writes evidence"),
    (EnvVar.TL_ARTIFACT_STEP.value, "The id of the running check"),
    (EnvVar.TL_RUN_ID.value, "The id of the run this command belongs to"),
    (EnvVar.TL_RUN_DIR.value, "The run's folder"),
    (EnvVar.TL_ATTEMPT.value, "The number of this attempt"),
    (EnvVar.TL_WORKTREE.value, "The worktree the run works in"),
    (EnvVar.TL_BRANCH.value, "The branch checked out in the worktree"),
    (EnvVar.TL_SLOT.value, "The slot's name"),
    (CHECK_LOG_PREFIX + "<ID>", "The log file of earlier check <ID>; upper-case id with each non-word run replaced by _"),
    (CHECK_RC_PREFIX + "<ID>", "The exit code of earlier check <ID>; upper-case id with each non-word run replaced by _"),
)
# The receipt layout (runtime.json and the run folder) is private to task-loop: consumers must use CONSUMER and tl check match only.
PRIVATE: Final = ("runtime.json",)
# Names a text may mention that are no variable: Python constants, and a name SKILL.md says is gone.
NOT_VARIABLES: Final = frozenset({"TL_PY", "TASK_LOOP_SUITE_HOST", "TASK_LOOP_SUITE_WORKERS", "TL_BOX_CWD", "TL_CHECKS_GREEN", "TL_LAND"})


def registered(name: str) -> bool:
    """Whether `name` is an engine variable: a member, or a family prefix with an id."""
    return name in EnvVar.__members__ or name.startswith(PREFIXES)
