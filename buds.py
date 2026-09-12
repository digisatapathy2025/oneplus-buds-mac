#!/usr/bin/env python3
"""
OnePlus Buds / HeyMelody Companion Application Launcher.
Unified entry point for Menu Bar Agent, Desktop Settings GUI, and CLI / TUI.
"""

import sys
import os

# Ensure current directory is in sys.path
_this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _this_dir and _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

CLI_FLAGS = {
    "-m", "--mode",
    "-l", "--level",
    "--game-mode",
    "--spatial-audio",
    "--bass-boost",
    "--in-ear",
    "--dual-connect",
    "--vocal-enhance",
    "--eq",
    "-i", "--interactive",
    "-s", "--scan",
    "-a", "--address",
    "--list-devices",
}


def print_help():
    print("""OnePlus Buds / HeyMelody Companion Application

Usage:
  buds.py [--menubar]           Run AirPods-style menu bar agent (default)
  buds.py --cli [options]       Execute CLI command or print status
  buds.py -i, --interactive     Launch interactive CLI control menu

Modes:
  --menubar                     Launch the native AppKit menu bar companion with
                                inline Bluetooth monitor and dynamic 0px collapse.
                                (All device controls and settings are built directly in)
  --cli                         Run headless CLI command over IPC or standalone BLE.

CLI Options:
  -i, --interactive             Interactive text control menu
  -m, --mode <mode>             Set Noise Mode: high, moderate, low, auto, off, transparency
  -l, --level <level>           Set ANC Intensity: mild, moderate, smart
  --game-mode <on|off>          Enable/disable Game Mode (low latency)
  --spatial-audio <on|off>      Enable/disable Spatial Audio (3D sound)
  --bass-boost <on|off>         Enable/disable BassWave
  --in-ear <on|off>             Enable/disable In-Ear wear detection
  --dual-connect <on|off>       Enable/disable Dual Connection
  --vocal-enhance <on|off>      Enable/disable Vocal Enhancement
  --eq <preset>                 Set Sound Master EQ: Balanced, Bass, Clear, Bold
  --list-devices                List all 82 supported OnePlus / OPPO / Realme models
  -s, --scan                    Force standalone BLE scan (bypassing menu bar IPC)
  -a, --address <addr>          Target specific BLE address or UUID
""")


def main():
    args = sys.argv[1:]

    # Help flag
    if any(a in ["-h", "--help"] for a in args):
        print_help()
        return

    # 1. Deprecated GUI Mode
    if "--gui" in args:
        print("Note: Standalone GUI is deprecated. All controls are now natively integrated in the menu bar dropdown.")
        return

    # 2. CLI Mode (explicit --cli, or any CLI flag present)
    is_cli = "--cli" in args or any(a in CLI_FLAGS for a in args)
    if is_cli:
        cli_args = [a for a in args if a != "--cli"]
        import core.cli
        core.cli.main(cli_args)
        return

    # 3. Explicit Menubar flag
    if "--menubar" in args:
        import core.menubar
        core.menubar.main()
        return

    # 4. Default (no flags): If menu bar agent is already running, notify user
    try:
        from core.ipc import BudsIPCClient
        if BudsIPCClient.is_server_active():
            print("OnePlus Buds Menu Bar companion is already running in your macOS menu bar.")
            print("Click the earbud icon in your menu bar to view and adjust all controls.")
            return
    except Exception:
        pass

    # Otherwise start Menu Bar Agent
    import core.menubar
    core.menubar.main()


if __name__ == "__main__":
    main()

