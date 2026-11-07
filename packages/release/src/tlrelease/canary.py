"""Origin-backed canary acknowledgements authorize the Mac standing pin."""
from pathlib import Path

from tlkernel.gitport import Git
from tlkernel.slots import SlotGitError

from tlrelease import clone, publish
from tlrelease.catalog import version_tuple
from tlrelease.shell import Abort, Shell


def devbox_ok(config: Path, url: str, version: str, sh: Shell) -> None:
    if version_tuple(version) is None:
        raise Abort("expected a release version MAJOR.MINOR.PATCH")
    where = clone.ready(config, url, sh)
    release, ack = "refs/tags/v" + version, "refs/tags/devbox-ok/v" + version
    refs = publish.git_must(lambda: sh.port.ls_remote(str(where), "origin", release, ack), where)
    found = {r.name: r.oid for r in refs}
    oid = found.get(release)
    if not oid:
        raise Abort(f"no release tag recorded on origin for {version}")
    if ack in found:
        if found[ack] != oid:
            raise Abort(f"devbox-ok tag for {version} does not match its release")
    else:
        publish.git_must(lambda: sh.port.push(str(where), "origin", oid + ":" + ack), where)


def mac_pin_refusal(where: Path, url: str, version: str, git: Git) -> str:
    if version_tuple(version) is None:
        return "expected a release version MAJOR.MINOR.PATCH"
    release, ack = "refs/tags/v" + version, "refs/tags/devbox-ok/v" + version
    try:
        refs = {r.name: r.oid for r in git.ls_remote(str(where), url, release, ack)}
    except SlotGitError as e:
        return f"refused: cannot read origin's devbox acknowledgement: {e}"
    ready = refs.get(release) and refs.get(release) == refs.get(ack)
    return "" if ready else f"refused: {version} needs devbox-ok before the Mac standing pin moves"
