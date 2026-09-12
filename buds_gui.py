#!/usr/bin/env python3
"""
OnePlus Buds Settings.
All device controls are now directly accessible via the native macOS Menu Bar dropdown.
"""
import sys
import os

_this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
for d in [_this_dir, os.path.join(_this_dir, "..", "Resources"), "/Users/digvijayasatapathy/HeyMelody_unpacked"]:
    if d and os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

def main():
    print("OnePlus Buds: All device settings and controls are now integrated directly into the macOS Menu Bar dropdown.")
    print("Click the earbud icon in your menu bar to manage Noise Cancellation, Spatial Audio, EQ, and Features.")

if __name__ == "__main__":
    main()
