"""python3 -m taskloop_dash [--port N] [--bind A,B] [--ports MODULE:FUNC]"""

from taskloop_dash.cli import dash

if __name__ == "__main__":
    dash.main()
