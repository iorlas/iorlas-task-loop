#!/bin/sh
# docscheck prototype runner: a2kay's venv python (3.12, has pydantic/jsonschema/ruamel/markdown-it) + shelf libs on PYTHONPATH.
# usage: ./run.sh [check|generate] [--all] [--changed PATH...] [--base REF]
P="$(cd "$(dirname "$0")" && pwd)"
S=/home/iorlas/Workspaces/shelf/packages
REPO=${DOCSCHECK_REPO:-/home/iorlas/Workspaces/iorlas-task-loop-b83c5d9a3f13cb9d/sleepy-nobel-d00460}
PYTHONPATH="$P/src:$S/any-frontmatter/src:$S/any-markdown/src:$S/any-path-glob/src" \
  exec /home/iorlas/Workspaces/a2kay/.venv/bin/python -m docscheck "${1:-check}" --docs "${DOCSCHECK_DOCS:-$P/docs}" --ontology "$P/ontology" --repo "$REPO" "${@:2}"
