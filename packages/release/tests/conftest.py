"""Declare the release's database part for standalone package tests."""
from tlkernel import factorydb
from tlkernel.factoryparts import RELEASE

factorydb.declare_parts((RELEASE,))
