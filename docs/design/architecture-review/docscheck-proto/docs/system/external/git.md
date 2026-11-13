---
# Status: evidence; historical format specimen, not current system authority
owns_facts: [commits, branches, worktrees, remote refs]
port: src/taskloop/git_views.py
used_by: [area/engine, area/storage]
rules:
  - {id: 1, applies_to: "every module outside commit, prepare, release, publish, environment and land", holds: "writes no Git state", check: "check/test_only_the_commit_prepare_release_publish_environment_and_land_modules_write_git"}
  - {id: 2, applies_to: "a push", holds: "is never forced and never lands the task; landing is [[term/land]]"}
---
