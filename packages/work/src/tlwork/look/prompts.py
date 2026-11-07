"""The look judge's texts: what a visual write is told to name, and the defects it is sent back with."""
from typing import Final

LOOK_WRITE_TABLE = ("\nThis stage changes how something looks (it touches visual paths). You cannot render it here: the engine does, "
                    "right after this write, and a look judge reads the pictures. Say what to render in `shots`: one entry per "
                    "set of pictures, with a method from the table below, its args (name, value) and names (the screens or "
                    "states you changed, in words). At most %d entries. Do not save screenshots yourself.\n%s\nIf nothing on "
                    "screen differs, leave `shots` empty and put a one-line reason in logic_only.")

LOOK_FEEDBACK: Final = ("\nThe engine rendered your shots and the look judge found these defects:\n%s\nThe pictures are at (open one only "
                 "if you need to):\n%s\nFix what the judge saw, and list the shots to render again in `shots`.\n")
