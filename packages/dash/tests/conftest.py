"""Declare the dashboard-owned database parts, and the look part its wake tests write through, for isolated tests."""
from tlkernel import factorydb
from tlkernel.factoryparts import LOOK

from tldash.parts import DASH_PARTS

factorydb.declare_parts((*DASH_PARTS, LOOK))
