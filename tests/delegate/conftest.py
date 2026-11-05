"""The delegate tests import their helpers (hermetic, routing_support, run_support) by flat name: this folder is on sys.path for every test below it."""
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
