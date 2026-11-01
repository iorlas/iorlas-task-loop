"""A typed loop environment for tests exercising only slot preparation and recovery."""
from typing import Never

import support.paths  # noqa: F401
from taskloop.app.loop.env import LoopEnv
from taskloop.app.slots.env import SlotEnv


def unused(*args: object, **kwargs: object) -> Never:
    raise AssertionError("this test does not provide that loop effect")


def slot_loop_env(env: SlotEnv) -> LoopEnv:
    """Use the slot's ports; fail loudly if the loop asks for an unrelated effect."""
    return LoopEnv(
        repo=env.repo, repo_key=env.repo_key, cfgdir=env.cfgdir, store=env.store,
        slot_env=lambda: env, profile=unused, fetch=unused, lint=unused, running=unused,
        area_lock=unused, wt_lock=unused, start_worktree=unused, claim=unused,
        loop_lock=unused, drop_engine_lock=unused, spawn=unused, stop_now=unused,
        stop_tree=unused, run_task_argv=unused, landed_on_base=unused, reload_note=unused,
        chores=unused, release_dead=unused, ask_lines=unused, storm=unused,
        has_delegate=unused, probe=unused, roles=unused, event=env.event,
        pid_alive=unused, behind=unused, version="test", session_actor=env.actor,
        code_dir="", actor=lambda: env.actor, exec_into=unused, take_handover=unused,
        say=env.say, now=env.now, sleep=env.sleep, pid=env.pid)
