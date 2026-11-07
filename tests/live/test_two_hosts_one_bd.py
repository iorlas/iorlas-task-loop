"""Z06: bd claims are exclusive per machine, not per factory.

This observed collision lets two hosts claim the same bead before either pulls.
A repo-owner record (option A of tl-sqd3.23) is deliberately not built until an
owner decision. This test pins today's behaviour so a bd upgrade that changes it
shows up.
"""
import json
import os
import pwd
import shutil
import time

import pytest

from tltestkit.checked import run_checked

LIVE_PATH = os.pathsep.join(part for part in os.get_exec_path() if not os.path.basename(part).startswith("tl-nobd-"))
BD = shutil.which("bd", path=LIVE_PATH)


@pytest.mark.live
@pytest.mark.skipif(not BD or not shutil.which("git"), reason="real bd and git are required")
def test_two_hosts_claim_without_pulling_and_merge_last_write_wins(world):
    """Real bd 1.3.1 accepts both claims and preserves C's claim on C's pull."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("BEADS_")}
    # This characterization intentionally bypasses support.paths' fake-bd guard.
    env["PATH"] = LIVE_PATH
    # Mise needs the real home; cwd and BEADS_DIR keep bd state in the test world.
    env["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
    remote = (world / "remote").as_uri()
    hosts = {name: world / name for name in ("a", "c")}
    for host in hosts.values():
        host.mkdir()

    def run(name: str, *args: str):
        host = hosts[name]
        host_env = {**env, "BEADS_DIR": str(host / ".beads"), "BEADS_ACTOR": f"host-{name}"}
        argv: list[str] = [str(BD), *args[1:]] if args[0] == "bd" else list(args)
        return run_checked(argv, host, env=host_env, text=True, timeout=120)

    run("a", "git", "init")
    run("a", "bd", "init", "--prefix", "z", "-q")
    (hosts["a"] / ".beads").chmod(0o700)
    issue_id = json.loads(run("a", "bd", "create", "x", "--type=task", "--json").stdout)["id"]
    run("a", "bd", "dolt", "remote", "add", "origin", remote)
    run("a", "bd", "dolt", "push")

    beads_c = hosts["c"] / ".beads"
    beads_c.mkdir(mode=0o700)
    shutil.copyfile(hosts["a"] / ".beads" / "config.yaml", beads_c / "config.yaml")
    with (beads_c / "config.yaml").open("a") as config:
        config.write(f"\nsync.remote: {remote}\n")
    run("c", "git", "init")
    run("c", "bd", "bootstrap", "--yes")

    # Neither host pulls between bootstrap and these independently accepted claims.
    assert run("a", "bd", "update", issue_id, "--claim").returncode == 0
    # Give C a later timestamp even on bd's second-resolution merge clock.
    time.sleep(1.1)
    assert run("c", "bd", "update", issue_id, "--claim").returncode == 0
    run("a", "bd", "dolt", "commit", "-m", "a")
    run("a", "bd", "dolt", "push")
    run("c", "bd", "dolt", "commit", "-m", "c")
    pull = run("c", "bd", "dolt", "pull")
    assert "last-write-wins" in pull.stdout + pull.stderr
    issue = json.loads(run("c", "bd", "show", issue_id, "--json").stdout)[0]
    assert issue["assignee"] == "host-c"
    assert issue["status"] == "in_progress"
