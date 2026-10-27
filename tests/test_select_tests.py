"""The shadow selector prints a conservative set by feature path and leaves the gate alone."""

import io
import os
import shutil
import socket
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import select_tests  # noqa: E402

EVIDENCE = ROOT / ".task" / "tl-7y6.7.25" / "evidence"
_INVENTORY = None


def inventory():
    global _INVENTORY
    if _INVENTORY is None:
        loader = unittest.TestLoader()
        suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT / "tests"))
        found = []

        def walk(item):
            for test in item:
                if isinstance(test, unittest.TestSuite):
                    walk(test)
                else:
                    found.append(test.id())
        walk(suite)
        _INVENTORY = sorted(set(found))
    return _INVENTORY


def run_cli(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(ROOT / "dev" / "select_tests.py")] + list(args),
                          cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True)


def fixture(test_name):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / ("tmp-%s-%d" % (test_name, os.getpid()))
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


class CLITests(unittest.TestCase):
    def test_base_origin_main_lists_sorted_unique_ids_from_discovery(self):
        proc = run_cli("--base", "origin/main", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ids = proc.stdout.splitlines()
        self.assertTrue(ids)
        self.assertEqual(ids, sorted(set(ids)))
        self.assertLessEqual(set(ids), set(inventory()))

    def test_list_does_not_run_test_bodies(self):
        path = fixture("no-run")
        self.addCleanup(shutil.rmtree, path, True)
        marker = path / "ran-marker"
        (path / "test_tl.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n"
            "MARK = Path(__file__).with_name('ran-marker')\n"
            "class Plant(unittest.TestCase):\n"
            "    def test_body_marks_a_file(self):\n"
            "        MARK.write_text('ran')\n", encoding="utf-8")
        proc = run_cli("--tests-dir", str(path), "--paths", "tests/test_tl.py", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["test_tl.Plant.test_body_marks_a_file"])
        self.assertFalse(marker.exists())


class FallbackTests(unittest.TestCase):
    def test_unmapped_core_dev_config_and_plugin_paths_select_every_test(self):
        full = inventory()
        for changed in ("unknown/planted.py", "skills/task-loop/core/planted.py", "dev/planted_tool.py",
                        ".task-loop.json", ".claude-plugin/plugin.json"):
            with self.subTest(path=changed):
                proc = run_cli("--paths", changed, "--list")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.splitlines(), full)

    def test_shared_layers_flat_hub_and_unassigned_test_modules_select_every_test(self):
        full = inventory()
        for changed in ("tests/test_rules.py", "skills/task-loop/engine.py", "tests/test_engine.py",
                        "tests/fixtures/briefs/planted.json"):
            with self.subTest(path=changed):
                proc = run_cli("--paths", changed, "--list")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.splitlines(), full)


class MappingTests(unittest.TestCase):
    def test_a_feature_change_selects_its_tests_and_reverse_dependants_only(self):
        proc = run_cli("--paths", "skills/task-loop/checks/planted.py", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        modules = {test_id.split(".", 1)[0] for test_id in proc.stdout.splitlines()}
        self.assertLessEqual({"test_checks_speed", "test_check_trim", "test_stages", "test_verify_noblock",
                              "test_land_lock", "test_held_branch", "test_loop", "test_race_invariants"}, modules)
        self.assertIn("test_engine", modules)
        for unrelated in ("test_tl", "test_dash", "test_slots", "test_opencode", "test_renotify",
                          "test_release", "test_look"):
            self.assertNotIn(unrelated, modules)

    def test_downstream_follows_reverse_layer_dependencies(self):
        edges = {"core": set(), "checks": {"core"}, "write": {"core", "checks"},
                 "review": {"core", "checks"}, "land": {"core", "checks"}, "loop": {"checks"},
                 "dash": {"core"}}
        self.assertEqual(select_tests.downstream({"checks"}, edges),
                         {"checks", "write", "review", "land", "loop"})

    def test_an_incomplete_mapping_falls_back_to_every_test(self):
        features = {"checks": ["test_check_trim", "test_missing_module"]}
        all_ids = ["test_check_trim.Plant.test_body"]
        self.assertEqual(select_tests.select_ids(["skills/task-loop/checks/x.py"], features=features,
                                                 edges={"checks": set()}, all_ids=all_ids), all_ids)

    def test_an_incomplete_unrelated_feature_falls_back_to_every_test(self):
        features = {"checks": ["test_checks"], "dash": ["test_dash", "test_missing"]}
        all_ids = ["test_checks.Plant.test_body", "test_dash.Plant.test_body"]
        self.assertEqual(select_tests.select_ids(["skills/task-loop/checks/x.py"], features=features,
                                                 edges={"checks": set(), "dash": {"checks"}},
                                                 all_ids=all_ids), all_ids)

    def test_a_missing_dependency_entry_falls_back_to_every_test(self):
        features = {"checks": ["test_check_trim"], "write": ["test_stages"]}
        all_ids = ["test_check_trim.Plant.test_body", "test_stages.Plant.test_body"]
        self.assertEqual(select_tests.select_ids(["skills/task-loop/checks/x.py"], features=features,
                                                 edges={"checks": set()}, all_ids=all_ids), all_ids)


class PathTests(unittest.TestCase):
    def test_name_status_keeps_deleted_renamed_and_both_sides_of_a_copy(self):
        raw = "M\0staged.py\0D\0deleted.py\0R100\0old.py\0new.py\0C75\0source.py\0copied.py\0A\0added.py\0"
        self.assertEqual(select_tests.parse_name_status(raw),
                         {"staged.py", "deleted.py", "old.py", "new.py", "source.py", "copied.py", "added.py"})

    def test_changed_paths_adds_untracked_files_to_the_diff(self):
        answers = iter(["M\0staged.py\0D\0deleted.py\0R100\0old.py\0new.py\0",
                        "untracked.py\0"])
        with mock.patch.object(select_tests, "run_git", side_effect=lambda *a, **kw: next(answers)):
            self.assertEqual(select_tests.changed_paths("origin/main"),
                             ["deleted.py", "new.py", "old.py", "staged.py", "untracked.py"])


class OfflineTests(unittest.TestCase):
    def test_git_is_local_and_ignores_user_configuration_and_external_helpers(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(select_tests.subprocess, "run", side_effect=fake_run):
            self.assertEqual(select_tests.changed_paths("origin/main"), [])
        self.assertEqual(len(calls), 2)
        diff = " ".join(calls[0][0])
        self.assertIn("diff", diff)
        self.assertIn("--no-ext-diff", diff)
        self.assertIn("--no-textconv", diff)
        for forbidden in ("fetch", "pull", "clone", "ls-remote", "push"):
            self.assertNotIn(forbidden, diff)
        for command, kwargs in calls:
            self.assertEqual(command[0], "git")
            self.assertIn("--no-optional-locks", command)
            self.assertIn("core.excludesFile=" + os.devnull, command)
            self.assertFalse(kwargs.get("shell"))
            self.assertEqual(kwargs["cwd"], str(ROOT))
            env = kwargs["env"]
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
            self.assertEqual(env["GIT_CONFIG_SYSTEM"], os.devnull)
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertNotIn("GIT_EXTERNAL_DIFF", env)
            self.assertNotIn("GIT_CONFIG", env)

    def test_real_git_does_not_read_the_xdg_global_excludes_file(self):
        path = fixture("xdg-ignore")
        self.addCleanup(shutil.rmtree, path, True)
        probe = "tests/test_select_tests.py"
        (path / "git").mkdir()
        (path / "git" / "ignore").write_text(probe + "\n", encoding="utf-8")
        env = select_tests.git_env()
        env["XDG_CONFIG_HOME"] = str(path)
        env["HOME"] = str(path)
        baseline = ["git", "--no-optional-locks", "--no-pager", "check-ignore",
                    "--no-index", "--quiet", probe]
        ignored = subprocess.run(baseline, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        self.assertEqual(ignored.returncode, 0, ignored.stderr)
        selected = subprocess.run(select_tests.git_command(["check-ignore", "--no-index", "--quiet", probe]),
                                  cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True)
        self.assertEqual(selected.returncode, 1, selected.stderr)

    def test_selection_uses_no_network_and_no_user_config(self):
        home = os.path.expanduser("~")
        config = os.path.join(home, ".config")
        real_expand = os.path.expanduser

        def guarded_expand(path):
            expanded = real_expand(path)
            if expanded.startswith(config):
                raise AssertionError("read user config: %s" % expanded)
            return expanded

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
                mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("network")), \
                mock.patch.object(os.path, "expanduser", side_effect=guarded_expand), \
                mock.patch.object(select_tests, "run_git", side_effect=AssertionError("git")), \
                redirect_stdout(out), redirect_stderr(err):
            rc = select_tests.main(["--paths", "tests/test_check_trim.py", "--list"])
        self.assertEqual(rc, 0, err.getvalue())
        self.assertTrue(out.getvalue().strip())

    def test_a_git_failure_exits_nonzero_with_a_message(self):
        err = io.StringIO()
        with mock.patch.object(select_tests, "run_git", side_effect=OSError("no git")), redirect_stderr(err):
            rc = select_tests.main(["--base", "origin/main", "--list"])
        self.assertNotEqual(rc, 0)
        self.assertIn("cannot select safely", err.getvalue())

    def test_a_discovery_failure_exits_nonzero_with_a_message(self):
        path = fixture("broken-discovery")
        self.addCleanup(shutil.rmtree, path, True)
        (path / "test_broken.py").write_text("raise RuntimeError('planted discovery failure')\n",
                                            encoding="utf-8")
        proc = run_cli("--tests-dir", str(path), "--paths", "tests/test_broken.py", "--list")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("cannot select safely", proc.stderr)


if __name__ == "__main__":
    unittest.main()
