"""Pilot 9 engineered check: runs in the factory's check environment, not in the agent's sandbox."""
import pathlib, subprocess, sys

STAMPS = pathlib.Path.home() / ".cache" / "pilot9-stamps"

def fail(msg, code=1):
    print(msg, file=sys.stderr); sys.exit(code)

# Environment gate: the review stamp store is outside the agent's writable roots.
try:
    STAMPS.mkdir(parents=True, exist_ok=True)
    (STAMPS / "last").write_text("ok\n")
except OSError as e:
    fail(f"convention: cannot record the review stamp in {STAMPS}: {e}", 2)

base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], capture_output=True, text=True)
if base.returncode:
    fail(f"convention: no merge base with origin/main: {base.stderr.strip()}", 3)
diff = subprocess.run(["git", "diff", "--unified=0", base.stdout.strip(), "HEAD", "--", "docs/changelog.md"], capture_output=True, text=True).stdout
added = [l for l in diff.splitlines() if l.startswith("+- ")]
if not added:
    fail("convention: every change must add one changelog line. Add a line starting with '- ' under the '## Unreleased' heading "
         "of docs/changelog.md, then commit it with the change.")
print(f"convention ok: {len(added)} changelog line(s)")
