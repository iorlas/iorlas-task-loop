"""The registry: every TL_* and TASK_LOOP_* name the engine exports, hands over or reads. A name appears here once; the code, SKILL.md,
the docs and the prompts say it by this table (tests/rules/test_envvars.py holds the three equal)."""
from enum import StrEnum
from typing import Final


class EnvVar(StrEnum):
    # exported into every command of a bead / check
    TL_SLOT = "TL_SLOT"                          # the slot's name (domain/slot_env)
    TL_ARTIFACT_DIR = "TL_ARTIFACT_DIR"          # <run dir>/artifacts/<step>/attempt-N: where this attempt writes its logs and results
    TL_ARTIFACT_STEP = "TL_ARTIFACT_STEP"        # the id of the check that is running
    TL_RUN_ID = "TL_RUN_ID"                      # the id of the run a command belongs to (the run_id of its rows)
    TL_RUN_DIR = "TL_RUN_DIR"                    # the run's folder
    TL_ATTEMPT = "TL_ATTEMPT"                    # N of this attempt (the N of TL_ARTIFACT_DIR)
    TL_WORKTREE = "TL_WORKTREE"                  # the worktree the run works in
    TL_BRANCH = "TL_BRANCH"                      # the branch checked out in it
    TL_BOX_CWD = "TL_BOX_CWD"                    # the cwd of a check inside its container
    TL_WORKER_MB = "TL_WORKER_MB"                # address-space cap of each xdist worker (release suite)
    TL_LAND = "TL_LAND"                          # set by the engine's own push (and only by it): the pre-push hook lets it through
    # handovers between two processes of the engine (one typed record each, see contracts/env.py)
    TL_REEXEC = "TL_REEXEC"                      # the run that re-execs itself after a code update
    TL_LOOP_STATE = "TL_LOOP_STATE"              # the loop's state across its exec
    TL_RELEASE_REEXEC = "TL_RELEASE_REEXEC"      # set in the exec'd release: it never execs again
    TASK_LOOP_SLOT_BEAD = "TASK_LOOP_SLOT_BEAD"  # the bead whose slot this process holds
    TASK_LOOP_ACTOR = "TASK_LOOP_ACTOR"          # the loop's actor name, inherited by its run-tasks
    TASK_LOOP_SESSION = "TASK_LOOP_SESSION"      # the engine's or loop's session id
    TASK_LOOP_LOOP_PID = "TASK_LOOP_LOOP_PID"    # the pid of the loop a run-task belongs to
    TASK_LOOP_WORKER = "TASK_LOOP_WORKER"        # set to 1 in a worker's environment
    # settings the owner may set
    TASK_LOOP_DASH_BIND = "TASK_LOOP_DASH_BIND"
    TASK_LOOP_DASH_PORT = "TASK_LOOP_DASH_PORT"
    TASK_LOOP_DASH_DEV_PUBLIC = "TASK_LOOP_DASH_DEV_PUBLIC"
    TASK_LOOP_DASH_IDLE_H = "TASK_LOOP_DASH_IDLE_H"
    TASK_LOOP_SUITE_HOST = "TASK_LOOP_SUITE_HOST"
    TASK_LOOP_SUITE_WORKERS = "TASK_LOOP_SUITE_WORKERS"


# Families: a name made of a prefix and a check id (domain/checks/names.py builds them; a check reads an earlier one's log and exit code).
CHECK_LOG_PREFIX: Final = "TL_CHECK_LOG_"
CHECK_RC_PREFIX: Final = "TL_CHECK_RC_"
PREFIXES: Final = (CHECK_LOG_PREFIX, CHECK_RC_PREFIX)
TL_PREFIX: Final = "TL_"  # the names a check inside a container is given (app/checks/container.py)
# Names a text may mention that are no variable: Python constants, and a name SKILL.md says is gone.
NOT_VARIABLES: Final = frozenset({"TL_PY", "TL_PREFIX", "TL_CHECKS_GREEN"})


def registered(name: str) -> bool:
    """Whether `name` is an engine variable: a member, or a family prefix with an id."""
    return name in EnvVar.__members__ or name.startswith(PREFIXES)
