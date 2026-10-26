import sys
import unittest

if sys.version_info < (3, 12):
    raise unittest.SkipTest("src/taskloop is written for Python 3.12 and later")
