#!/usr/bin/env python3
"""One-release bridge: origin/main's release code still runs this path; it runs the native suite. The next release deletes it."""
import os
import sys

args = sys.argv[1:]
repo = args[args.index("--repo") + 1] if "--repo" in args else "."
os.chdir(repo)
os.execvp("uv", ["uv", "run", "--script", "dev/suite.py"])
