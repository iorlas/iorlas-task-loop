#!/usr/bin/env python3
"""Runs `just test`. It exists for one release only: the repo profile's suite check still names `uv run --script dev/suite.py`, and a
profile changes only by the owner. When the profile says `just test`, this file is deleted; it holds no logic of its own."""
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent.parent)
os.execvp("just", ["just", "test"])
sys.exit(1)
