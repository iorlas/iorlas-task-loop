#!/usr/bin/env python3
"""Print a conservative test selection for uncommitted changes; never run it and never touch the gate.

`python3 tools/select_tests.py --base origin/main --list` reads local Git state, maps
`skills/task-loop/<feature>/` and `tests/<feature>/` paths through tests/feature_tests.py,
adds the features that depend on the changed ones (tests/test_layers.py), and prints sorted
unittest ids. Unmapped paths, Core, tools/, .task-loop.json, a plugin.json, shared fixtures,
and flat hub modules fall back to the whole suite. Test modules without a feature stay in
every selection because they are integration coverage.

The selector is shadow-only: it reads no network and no user configuration, only local Git
with global/system config and external diff helpers disabled. Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FEATURE_TESTS = TESTS / "feature_tests.py"
LAYER_TESTS = TESTS / "test_layers.py"

FULL = object()
FULL_FILES = {".task-loop.json", "tests/test_layers.py", "release.py", "dev/release.py"}
FULL_PREFIXES = ("tools/", "tests/fixtures/", "Core/", "core/")
GIT_CONFIG = ("-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
              "-c", "core.excludesFile=" + os.devnull)
GIT_ENV_DROP = ("GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_PAGER", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS")


class SelectionError(Exception):
    pass


def _load(name, path):
    spec = importlib.util.spec_from_file_location("_tl_select_" + name, str(path))
    if spec is None or spec.loader is None:
        raise SelectionError("cannot load %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def feature_map(root=ROOT):
    path = Path(root) / "tests" / "feature_tests.py"
    features = _load("feature_tests", path).FEATURES
    return {name: list(tests) for name, tests in features.items()}


def layer_edges(root=ROOT):
    path = Path(root) / "tests" / "test_layers.py"
    return {name: set(deps) for name, deps in _load("test_layers", path).ALLOWED.items()}


def _walk(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _walk(test)
        else:
            yield test


def discover_ids(tests_dir=TESTS):
    loader = unittest.TestLoader()
    try:
        suite = loader.discover(str(tests_dir), top_level_dir=str(tests_dir))
    except (ImportError, OSError, SyntaxError) as error:
        raise SelectionError("test discovery failed: %s" % error)
    ids, broken = set(), []
    for test in _walk(suite):
        if type(test).__name__ == "_FailedTest":
            broken.append(str(test))
        else:
            ids.add(test.id())
    if broken:
        raise SelectionError("test discovery failed: %s" % "; ".join(sorted(broken)))
    return sorted(ids)


def feature_for_path(path, features):
    path = str(path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    parts = PurePosixPath(path).parts
    if not parts:
        return FULL
    if path in FULL_FILES or parts[-1] == "plugin.json":
        return FULL
    if path.startswith(FULL_PREFIXES):
        return FULL
    if len(parts) >= 2 and parts[0] == "skills" and parts[1] == "task-loop":
        if len(parts) < 3 or parts[2] not in features:
            return FULL
        return FULL if parts[2] == "core" else parts[2]
    if parts[0] == "tests":
        if len(parts) == 2 and parts[1].startswith("test_") and parts[1].endswith(".py"):
            module = parts[1][:-3]
            for feature, modules in features.items():
                if module in modules:
                    return feature
            return FULL
        if len(parts) >= 3 and parts[1] in features:
            return parts[1]
        return FULL
    return FULL


def downstream(start, edges):
    chosen = set(start)
    while True:
        grown = chosen | {name for name, deps in edges.items() if deps & chosen}
        if grown == chosen:
            return chosen
        chosen = grown


def select_ids(paths, features=None, edges=None, all_ids=None):
    features = feature_map() if features is None else features
    edges = layer_edges() if edges is None else edges
    all_ids = discover_ids() if all_ids is None else list(all_ids)
    if set(features) - set(edges):
        return sorted(set(all_ids))
    if {dep for deps in edges.values() for dep in deps} - set(features):
        return sorted(set(all_ids))
    discovered = {test_id.split(".", 1)[0] for test_id in all_ids}
    assigned = {module for tests in features.values() for module in tests}
    if assigned - discovered:
        return sorted(set(all_ids))
    changed = set()
    for path in paths:
        feature = feature_for_path(path, features)
        if feature is FULL:
            return sorted(set(all_ids))
        changed.add(feature)
    chosen = downstream(changed, {name: set(edges[name]) for name in features})
    modules = set()
    for feature in chosen:
        if feature not in features:
            return sorted(set(all_ids))
        modules.update(features[feature])
    modules |= discovered - assigned
    selected = [test_id for test_id in all_ids if test_id.split(".", 1)[0] in modules]
    return sorted(set(selected)) if selected else sorted(set(all_ids))


def git_env():
    env = os.environ.copy()
    for name in GIT_ENV_DROP:
        env.pop(name, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_PAGER"] = "cat"
    return env


def git_command(args):
    return ["git", "--no-optional-locks"] + list(GIT_CONFIG) + ["--no-pager"] + list(args)


def run_git(args, root=ROOT):
    command = git_command(args)
    try:
        result = subprocess.run(command, cwd=str(root), env=git_env(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except OSError as error:
        raise SelectionError("git failed: %s" % error)
    if result.returncode:
        raise SelectionError("git %s failed: %s" % (" ".join(args), (result.stderr or "").strip()))
    return result.stdout


def parse_name_status(raw):
    paths, fields, index = set(), raw.split("\0"), 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        width = 2 if status[0] in "RC" else 1
        if index + width > len(fields):
            raise SelectionError("git returned a truncated name-status record")
        paths.update(fields[index:index + width])
        index += width
    return paths


def changed_paths(base, root=ROOT):
    diff = run_git(["diff", "--name-status", "--find-renames", "--no-ext-diff", "--no-textconv",
                    "-z", base, "--"], root)
    paths = parse_name_status(diff)
    untracked = run_git(["ls-files", "--others", "--exclude-standard", "-z"], root)
    paths.update(path for path in untracked.split("\0") if path)
    return sorted(paths)


def read_paths(paths, stdin):
    if paths:
        return list(paths)
    raw = stdin.read()
    return [path for path in (raw.split("\0") if "\0" in raw else raw.splitlines()) if path]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the conservative unittest selection for a change.")
    parser.add_argument("--base", default="origin/main", help="Git revision to compare the worktree with")
    parser.add_argument("--list", action="store_true", help="print the sorted unittest ids")
    parser.add_argument("--paths", nargs="+", help="use these paths instead of reading Git")
    parser.add_argument("--paths-stdin", action="store_true", help="read paths from stdin instead of Git")
    parser.add_argument("--tests-dir", default=str(TESTS), help="directory to discover tests in")
    args = parser.parse_args(argv)
    if args.paths and args.paths_stdin:
        parser.error("--paths and --paths-stdin cannot be combined")
    try:
        if args.paths or args.paths_stdin:
            paths = read_paths(args.paths, sys.stdin)
        else:
            paths = changed_paths(args.base)
        tests_dir = Path(args.tests_dir)
        if not tests_dir.is_absolute():
            tests_dir = ROOT / tests_dir
        all_ids = discover_ids(tests_dir)
        selected = select_ids(paths, all_ids=all_ids)
    except (SelectionError, OSError) as error:
        print("cannot select safely: %s" % error, file=sys.stderr)
        return 2
    for test_id in selected:
        print(test_id)
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
