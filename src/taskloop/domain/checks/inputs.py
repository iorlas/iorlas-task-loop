"""What a check's green result is a fact about (its `inputs`), as a cache key. Pure: the file lists and digests come from outside.

Cache policy (tl-7y6.7.7): a green result is remembered per check as a fact about the files in its `inputs` (RunKey.inputs). Widen `inputs`,
never narrow: a glob that is too wide only costs a rerun, one that is too narrow serves a green over code the check never saw,
and a wrong cache hit is worse than a miss. A check with no `inputs` is keyed on the whole tree and base; a glob that matches no
tracked file switches the cache off for that round. Only a pass is stored, and a plan's own (acceptance) check is never cached:
it can read what git cannot see."""
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Final

from taskloop.contracts.checks import Check
from taskloop.domain.checks.matchers import expand_braces, glob_re, literal_prefix
from taskloop.domain.checks.names import norm

ROOT_FILES: Final = ("justfile", "Justfile", ".justfile", "*.lock", "packages-lock.json", "package-lock.json", "Directory.Packages.props",
              "Directory.Build.props", "Directory.Build.targets", "global.json", "nuget.config", ".task-loop.json")


def dead_globs(paths: Iterable[str], globs: Iterable[str]) -> list[str]:
    """The globs that match none of `paths` (tracked files): a typo, or a dialect the glob does not speak."""
    have = list(paths)
    res = [(g, glob_re(g)) for g in globs]
    return [g for g, r in res if not any(r.match(p) for p in have)]


def inputs_hash(files: Mapping[str, str], globs: Iterable[str], exclude: Iterable[str] = ()) -> str:
    """Hash of the files ({path: "mode sha"}) that match any glob and no exclude. Empty when nothing matches: a check whose inputs
    are not in the tree has no fact to remember."""
    h = hashlib.sha1()
    n = 0
    res, ex = [glob_re(g) for g in globs], [glob_re(g) for g in exclude]
    for p in sorted(files):
        if any(r.match(p) for r in res) and not any(r.match(p) for r in ex):
            h.update((f"{files[p]}\t{p}\0").encode("utf-8", "surrogateescape"))
            n += 1
    return h.hexdigest() if n else ""


def pathspec(globs: Iterable[str], exclude: Iterable[str] = ()) -> list[str]:
    """What to ask git for the ignored files under the globs: their literal folders (`client/Assets/{App,Core}/**` ->
    client/Assets/App/, client/Assets/Core/), so a Library/ the globs do not name is never walked; a glob with no literal folder
    lists the whole tree. Excluded folders are pruned where git can."""
    alts = [x for g in globs for x in expand_braces(g)]
    prefixes = sorted({literal_prefix(x) for x in alts})
    spec = [] if "" in prefixes else [":(literal)" + p for p in prefixes]
    ex = [":(exclude,glob)" + x for g in exclude for x in expand_braces(g)]
    return (spec or [":(literal)."]) + ex if ex else spec


def matching(paths: Iterable[str], globs: Iterable[str], exclude: Iterable[str] = ()) -> list[str]:
    """The paths that match any glob and no exclude."""
    res, ex = [glob_re(g) for g in globs], [glob_re(g) for g in exclude]
    return [p for p in paths if p and any(x.match(p) for x in res) and not any(x.match(p) for x in ex)]


WHOLE_TREE: Final = "-"  # reads_digest of a check without `inputs`: the key's `tree` says which files
TOOLCHAIN_FILES: Final = ("mise.toml", ".mise.toml", ".tool-versions", ".python-version", ".node-version", ".nvmrc", "rust-toolchain",
                          "rust-toolchain.toml", "global.json")


def reads_digest(check: Check, files: Mapping[str, str], ignored: Mapping[str, str]) -> str:
    """What one check reads, as a digest: with `inputs` the hash of the tree files matching them, of the gitignored files matching
    them (`ignored`: path -> content digest; tree_hash never sees them), and unless `inputs_only` also of the justfile, lockfiles and
    .task-loop.json anywhere in the tree. WHOLE_TREE for a check without `inputs` (the key's `tree` says which). '' = it reads
    nothing that is there: no fact to remember. The command is the key's `cmd`, not here."""
    globs = list(check.inputs)
    if not globs:
        return WHOLE_TREE
    h = hashlib.sha1()
    excl = list(check.exclude)
    ih = inputs_hash(files, globs, excl)
    if not ih and not ignored:
        return ""
    for p in sorted(ignored):
        h.update((f"I\t{p}\t{ignored[p]}\0").encode("utf-8", "surrogateescape"))
    h.update(f"\0{ih}\0{chr(0).join(excl)}".encode("utf-8", "surrogateescape"))
    if not check.inputs_only:
        h.update(inputs_hash(files, ["*/" + g for g in ROOT_FILES] + list(ROOT_FILES)).encode())
    return h.hexdigest()


def cmd_digest(check: Check) -> str:
    return hashlib.sha1(norm(check.cmd).encode("utf-8", "surrogateescape")).hexdigest()


def config_digest(check: Check) -> str:
    """The declared settings of a check that change what it reads or where it runs: a changed glob, exclude, inputs_only, container or
    fix command is another check, whatever its id."""
    text = json.dumps([list(check.inputs), list(check.exclude), check.inputs_only, check.container, check.fix], separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8", "surrogateescape")).hexdigest()


def selected_digest(check: Check) -> str:
    """The tests the command resolved to ('' when it runs all of them): another set is another run."""
    return hashlib.sha1("\0".join(sorted(check.selected)).encode("utf-8", "surrogateescape")).hexdigest() if check.selected else ""


def toolchain_digest(files: Mapping[str, str], host: str) -> str:
    """The toolchain a check ran under: the host (system and machine) and the pin files of the tree (mise, python, node, rust, dotnet),
    at any depth. A bumped pin reruns even a check whose `inputs_only` leaves the rest of the tree out."""
    pins = ["*/" + g for g in TOOLCHAIN_FILES] + list(TOOLCHAIN_FILES)
    return hashlib.sha1(f"{host}\0{inputs_hash(files, pins)}".encode("utf-8", "surrogateescape")).hexdigest()


def touched(check: Check, changed: Iterable[str]) -> bool:
    """True when the diff (`changed`: paths) changes what the check reads: any path for a check with no `inputs` (it reads the whole
    tree), else a path under its inputs, or (unless `inputs_only`) one of the root files its cache key also reads."""
    paths = [p for p in changed if p]
    if not check.inputs:
        return bool(paths)
    own = bool(matching(paths, check.inputs, check.exclude))
    return own or (not check.inputs_only and bool(matching(paths, ["*/" + g for g in ROOT_FILES] + list(ROOT_FILES))))
