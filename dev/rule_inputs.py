"""Rule inputs: broad scans always run; bounded scans follow paths or import closure."""
from fnmatch import fnmatchcase

ALWAYS_RULES = {
    "tests/rules/gate_rules.py",
    "tests/rules/real/test_changed_files.py",
    "tests/rules/real/test_closure_ratchet.py",
    "tests/rules/real/test_host_ban_list.py",
    "tests/rules/real/test_layout_lock.py",
    "tests/rules/real/test_quarantine_ratchet.py",
    "tests/rules/real/test_ratchets_change.py",
    "tests/rules/test_rule_classes.py",
    "tests/rules/test_arch_invariants.py",
    "tests/rules/test_arch_rules.py",
    "tests/rules/test_dash_state_paths.py",
    "tests/rules/test_engine_order.py",
    "tests/rules/test_enumtotal.py",
    "tests/rules/test_env_below_edge.py",
    "tests/rules/test_envvars.py",
    "tests/rules/test_factorydb_owners.py",
    "tests/rules/test_gatepass_rule.py",
    "tests/rules/test_git_ratchet.py",
    "tests/rules/test_locks_rule.py",
    "tests/rules/test_no_branch_literals.py",
    "tests/rules/test_no_consumer_names.py",
    "tests/rules/test_no_cross_module_assignment.py",
    "tests/rules/test_no_force_push.py",
    "tests/rules/test_no_global_sleep_patch.py",
    "tests/rules/test_no_kind_strings.py",
    "tests/rules/test_no_os_services.py",
    "tests/rules/test_no_whole_suite_command.py",
    "tests/rules/test_one_reader.py",
    "tests/rules/test_one_repo_key.py",
    "tests/rules/test_package_surface.py",
    "tests/rules/test_package_tests.py",
    "tests/rules/test_pause_reasons.py",
    "tests/rules/test_ports_only.py",
    "tests/rules/test_root_ratchet.py",
    "tests/rules/test_root_totals.py",
    "tests/rules/test_runstate_rule.py",
    "tests/rules/test_selection_mutations.py",
    "tests/rules/test_stage_parts.py",
    "tests/rules/test_state_writers.py",
    "tests/rules/test_store_path.py",
    "tests/rules/test_subprocess_rule.py",
    "tests/rules/test_task_ids.py",
    "tests/rules/test_type_ratchet.py",
}

# SELF helpers are named here for review; imports/mentions normally supply their edges.
RULES_BY_PATH = {
    "tests/rules/test_cpu_rerun.py": (
        "tests/conftest.py",
    ),
    # dev/affected.py, dev/importgraph.py
    "tests/rules/test_affected_closure.py": (
    ),
    # tests/rules/closure_ratchet.py
    "tests/rules/test_closure_ratchet.py": (
    ),
    "tests/rules/test_dash_engine_sql.py": (
        "packages/dash/src/tldash/**",
        "packages/kernel/src/tlkernel/tableowners.py",
    ),
    "tests/rules/test_dash_tests_isolated.py": (
        "packages/dash/tests/**",
    ),
    "tests/rules/test_dash_xss.py": (
        "packages/dash/src/tldash/static/**/*.js",
        "packages/dash/src/tldash/static/**/*.html",
    ),
    "tests/rules/test_dashboard_verbs.py": (
        "packages/dash/src/tldash/static/index.html",
        "packages/dash/src/tldash/static/js/**",
        "skills/task-loop/tl.py",
        "src/taskloop/cli/**",
    ),
    # tests/support/scope.py
    "tests/rules/test_delegate_scope.py": (
    ),
    "tests/rules/test_doc_contract_version.py": (
        "packages/delegate/src/delegate/contracts/wire.py",
        "docs/dev/integrations.md",
        "packages/delegate/docs/contracts/delegate-api.md",
        "README.md",
        "CLAUDE.md",
    ),
    # dev/flakes.py
    "tests/rules/test_flakes.py": (
    ),
    "tests/rules/test_host_ban.py": (
        ".importlinter",
        "tests/rules/*.py",
        "packages/artifacts/src/*/**/*.py",
        "packages/artifacts/ruff.toml",
        "packages/gate/src/*/**/*.py",
        "packages/gate/ruff.toml",
        "packages/pipeline/src/*/**/*.py",
        "packages/pipeline/ruff.toml",
        "packages/work/src/*/plan/**/*.py",
        "packages/work/src/*/review/**/*.py",
        "packages/work/ruff.toml",
        "src/taskloop/app/checks/**/*.py",
        "src/taskloop/app/doctor/**/*.py",
        "src/taskloop/app/doctor/ruff.toml",
        "src/taskloop/app/loop/**/*.py",
        "src/taskloop/app/loop/ruff.toml",
        "src/taskloop/app/reconcile/**/*.py",
        "src/taskloop/app/reconcile/ruff.toml",
        "packages/areas/**",
        "packages/release/src/**/*.py",
        "packages/release/ruff.toml",
    ),
    "tests/rules/test_kernel_has_no_effects.py": (
        "packages/kernel/src/tlkernel/**/*.py",
    ),
    "tests/rules/test_land_asserts_tree.py": (
        "packages/land/src/tlland/stack.py",
    ),
    # tests/rules/layout_lock.py
    "tests/rules/test_layout_lock.py": (
    ),
    "tests/rules/test_one_test_command.py": (
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "skills/task-loop/SKILL.md",
        "packages/work/src/tlwork/prompts/*.py",
        "packages/work/src/tlwork/write/review_prompt.py",
        "packages/work/src/tlwork/review/verify_prompt.py",
        "packages/pipeline/src/tlpipeline/reflect_prompt.py",
    ),
    "tests/rules/test_package_test_env.py": (
        "packages/*/tests/**",
        "packages/*/pyproject.toml",
    ),
    # dev/packages.py
    "tests/rules/test_packages_selection.py": (
    ),
    "tests/rules/test_paths_no_stage_names.py": (
        "packages/kernel/src/tlkernel/paths.py",
    ),
    "tests/rules/test_pep723.py": (
        "pyproject.toml",
        "skills/task-loop/tl.py",
        "hooks/hook.py",
        "dev/release.py",
        "dev/race.py",
        "dev/dash_fixtures.py",
    ),
    # packages/testkit/src/tltestkit/procsim.py
    "tests/rules/test_procsim.py": (
    ),
    "tests/rules/test_queue_terms.py": (
        "packages/land/src/tlland/domain/queue*.py",
        "packages/land/src/tlland/queue*.py",
    ),
    # tests/rules/layer_ratchet.py, tests/rules/needs_ratchet.py, tests/rules/temp_ratchet.py, tests/rules/ratchet_change.py
    "tests/rules/test_ratchets.py": (
    ),
    # dev/reach.py, dev/affected.py
    "tests/rules/test_reach.py": (
    ),
    # packages/testkit/src/tltestkit/procsim.py
    "tests/rules/real/test_procsim.py": (
        "packages/testkit/src/tltestkit/procsim.py",
    ),
    # tests/rules/ratchet_change.py
    "tests/rules/real/test_texts_at.py": (
    ),
    # packages/testkit/src/tltestkit/waits.py
    "tests/rules/real/test_waits_helper.py": (
    ),
    # packages/testkit/src/tltestkit/wall.py
    "tests/rules/real/test_wall_guard.py": (
        "packages/testkit/src/tltestkit/wall.py",
    ),
    "tests/rules/real/test_work_boundary.py": (
        ".importlinter",
        "mise.toml",
    ),
    "tests/rules/test_roots_classified.py": (
        ".importlinter",
        "src/taskloop/*/__init__.py",
        "src/taskloop/app/*/__init__.py",
        "packages/*/src/*/**/__init__.py",
        "src/taskloop/app/run/*.py",
        "src/taskloop/app/launch/*.py",
        "src/taskloop/app/wire/*.py",
    ),
    "tests/rules/test_round_handoffs.py": (
        "packages/work/src/tlwork/plan/**",
        "packages/work/src/tlwork/review/**",
        "packages/work/src/tlwork/write/**",
        "packages/work/src/tlwork/look/**",
    ),
    # dev/runtests.py
    "tests/rules/test_runtests_env.py": (
    ),
    # dev/runtests.py, dev/affected.py
    "tests/rules/test_runtests_ledger.py": (
    ),
    # dev/runtests.py
    "tests/rules/test_runtests_nice.py": (
    ),
    # dev/runtests.py
    "tests/rules/test_runtests_workers.py": (
    ),
    "tests/rules/test_stage_entry.py": (
        "src/taskloop/app/run/*.py",
        "src/taskloop/app/launch/*.py",
        "packages/pipeline/src/tlpipeline/*.py",
    ),
    # packages/kernel/src/tlkernel/scratch.py
    "tests/rules/test_temp_ratchet.py": (
    ),
    # tests/conftest.py, packages/testkit/src/tltestkit/plugin.py
    "tests/rules/test_tempdir_cache.py": (
        "packages/testkit/src/tltestkit/plugin.py",
    ),
    # tests/conftest.py, packages/testkit/src/tltestkit/plugin.py
    "tests/rules/test_test_isolation.py": (
        "packages/testkit/src/tltestkit/plugin.py",
    ),
    # dev/test_pkg.py
    "tests/rules/test_test_pkg.py": (
    ),
    # dev/testtimes_report.py
    "tests/rules/test_testtimes_report.py": (
    ),
    "tests/rules/test_tree_writer.py": (
        "packages/gate/src/tlgate/*.py",
    ),
    # packages/testkit/src/tltestkit/waits.py, packages/testkit/src/tltestkit/memdoc.py
    "tests/rules/test_waits_helper.py": (
    ),
    # tests/rules/writer_invariants.py
    "tests/rules/test_writer_invariants.py": (
    ),
}


def matches(path, pattern):
    """Match repository path components; ** consumes zero or more components."""
    return _match(tuple(path.split("/")), tuple(pattern.split("/")))


def _match(parts, globs):
    if not globs:
        return not parts
    if globs[0] == "**":
        return _match(parts, globs[1:]) or (bool(parts) and _match(parts[1:], globs))
    return bool(parts) and fnmatchcase(parts[0], globs[0]) and _match(parts[1:], globs[1:])
