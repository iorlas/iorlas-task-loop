#!/usr/bin/env python3
"""delegate entry script: what a worker's guard shim runs (`entry.py guard ...`); the code is the package next to it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delegate.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
