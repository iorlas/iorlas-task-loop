"""Helpers for the engine's check rounds: what a check's result is a fact about (its inputs), what a check costs
(duration history), and which checks repeat another. Pure functions and small files; no engine state."""

import fnmatch
import hashlib
import subprocess

import tl


def norm(cmd):
    return " ".join(str(cmd).split())


# --- per-check input hash -------------------------------------------------------------------------------------------

def tree_files(wt, tree):
    """{path: "mode sha"} for a git tree, from `git ls-tree -r -z`."""
    r = subprocess.run(["git", "ls-tree", "-r", "-z", tree], cwd=wt, env=tl.git_env(wt), capture_output=True)
    out = {}
    for ent in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        meta, _, path = ent.partition("\t")
        if path:
            out[path] = meta
    return out


def inputs_hash(files, globs):
    """Hash of the files in `files` ({path: "mode type sha"}) that match any glob (fnmatch, as a check's `when`: `*`
    crosses `/`). Empty when nothing matches: a check whose inputs are not in the tree has no fact to remember."""
    h = hashlib.sha1()
    n = 0
    for p in sorted(files):
        if any(fnmatch.fnmatch(p, g) for g in globs):
            h.update(("%s\t%s\0" % (files[p], p)).encode("utf-8", "surrogateescape"))
            n += 1
    return h.hexdigest() if n else ""


def input_key(cmd, files, globs):
    """What a green result of `cmd` is a fact about: the command and the hash of its input files. "" = no key."""
    ih = inputs_hash(files, globs)
    return hashlib.sha1(("%s\0%s" % (norm(cmd), ih)).encode("utf-8", "surrogateescape")).hexdigest() if ih else ""
