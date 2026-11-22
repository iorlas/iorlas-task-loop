import os, sys, unittest
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
unittest.main(module="accept_cases", argv=["accept", "-q"])
