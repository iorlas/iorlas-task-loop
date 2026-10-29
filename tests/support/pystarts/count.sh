#!/usr/bin/env bash
# count.sh OUT [pytest args]: runs the suite with every Python start in it noted to OUT, prints the count (see probe.py).
set -euo pipefail
out=$(realpath -m "$1"); shift
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
site=$(cd "$root" && uv run python -c 'import site; print(site.getsitepackages()[0])')
pth="$site/zz_pystarts.pth"
: > "$out"
printf "import sys; sys.path.append('%s'); import probe; probe.note('%s')\n" "$here" "$out" > "$pth"
trap 'rm -f "$pth"' EXIT
(cd "$root" && uv run pytest "$@" || true)
wc -l < "$out"
