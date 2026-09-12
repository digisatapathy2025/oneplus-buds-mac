#!/usr/bin/env python3
"""
OnePlus Buds Menu Bar Application.
Forwarding wrapper to unified buds.py / core.menubar.
"""
import sys
import os

_this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
for d in [_this_dir, os.path.join(_this_dir, "..", "Resources"), "/Users/digvijayasatapathy/HeyMelody_unpacked"]:
    if d and os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

import core.menubar

def main():
    core.menubar.main()

if __name__ == "__main__":
    main()
