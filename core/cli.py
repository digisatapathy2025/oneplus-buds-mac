#!/usr/bin/env python3
"""
Unified CLI & Interactive TUI for OnePlus / OPPO / Realme Earbuds.
Supports both IPC attachment to the menu bar agent and standalone Bleak execution.
"""

import os
import sys
import json
import time
import asyncio
import argparse
from typing import Optional, Dict, Any, List

from core.protocol import (
    BudsProtocol,
    NOISE_MODES,
    PRIMARY_NOISE_MODES,
    ANC_MODES,
    EQ_PRESETS,
    FEATURE_IN_EAR,
    FEATURE_GAME_MODE,
    FEATURE_VOCAL_ENHANCE,
    FEATURE_DUAL_CONNECT,
    FEATURE_SPATIAL_AUDIO,
    FEATURE_BASS_ENGINE,
    FEATURE_NAMES,
    normalize_noise_mode,
)
from core.ble_controller import BaseBudsController, BudsState, CONFIG_FILE
from core.ipc import BudsIPCClient
from core.transport_bleak import BleakTransport, discover_supported_earbuds
from device_manager import (
    DeviceProfile, DEFAULT_PROFILE, get_device_profile,
    match_supported_device, is_supported_device, CATALOG_DATA
)


def print_device_catalog():
    print(f"\n{'=' * 68}")
    print(f" Supported Devices Catalog ({len(CATALOG_DATA)} models across OnePlus / OPPO / Realme)")
    print(f"{'=' * 68}\n")
    cats = {
        "T1": "ANC True Wireless Earbuds (T1)",
        "T2": "Standard True Wireless Earbuds (T2)",
        "O1": "Open-Ear Clip & Sport Audio (O1)",
        "N": "Wireless Neckbands (N)"
    }
    for cat_code, cat_title in cats.items():
        devs = [d for d in CATALOG_DATA if d.device_type == cat_code]
        print(f"▶ {cat_title} — {len(devs)} Models:")
        for d in devs:
            name = d.name
            pid = d.product_id
            brand = d.brand
            features = []
            if d.has_anc: features.append("ANC")
            if d.has_spatial: features.append("Spatial")
            if d.has_bass_boost: features.append("BassWave")
            if d.has_dual_connect: features.append("DualLink")
            f_str = f" [{', '.join(features)}]" if features else ""
            print(f"   • {name:<36} ID: {pid:<8} ({brand}){f_str}")
        print()


def print_status_box(state_dict: Dict[str, Any]):
    name = state_dict.get("name", "OnePlus Buds")
    pid = state_dict.get("product_id", "")
    prof = get_device_profile(pid or name) or DEFAULT_PROFILE

    print("\n┌────────────────────────────────────────────────────────┐")
    dev_title = f"{prof.name} ({prof.category_title})"
    if len(dev_title) > 52:
        dev_title = dev_title[:49] + "..."
    print(f"│  {dev_title:<54}│")
    print("├────────────────────────────────────────────────────────┤")

    # Battery
    b = state_dict.get("battery", {})
    if prof.is_neckband:
        single = b.get("single", b.get("left", {}))
        s_str = f"{single.get('level', '?')}%{' ⚡' if single.get('charging') else ''}" if single else "N/A"
        print(f"│  🔋 Battery:                                           │")
        print(f"│     • Neckband Battery : {s_str:<29} │")
    else:
        left = b.get("left", {})
        right = b.get("right", {})
        case = b.get("case", {})

        l_str = f"{left.get('level', '?')}%{' ⚡' if left.get('charging') else ''}" if left.get("connected") else "--%"
        r_str = f"{right.get('level', '?')}%{' ⚡' if right.get('charging') else ''}" if right.get("connected") else "--%"
        c_str = f"{case.get('level', '?')}%{' ⚡' if case.get('charging') else ''}" if case.get("connected") else "--%"

        print(f"│  🔋 Battery:                                           │")
        print(f"│     • Left Earbud : {l_str:<12} Right Earbud: {r_str:<10} │")
        print(f"│     • Case        : {c_str:<32} │")

    print("├────────────────────────────────────────────────────────┤")

    # Noise Control
    if prof.has_anc:
        cur_noise = (state_dict.get("current_noise_mode") or state_dict.get("last_primary_mode") or "Auto").upper()
        print(f"│  🎧 Noise Control: {cur_noise:<35}│")
        print("├────────────────────────────────────────────────────────┤")

    # Features
    feats = state_dict.get("features", {})
    print("│  🎛️  Feature Switches:                                  │")
    for fid, fname in FEATURE_NAMES.items():
        supported = True
        if fid == FEATURE_SPATIAL_AUDIO and not prof.has_spatial: supported = False
        elif fid == FEATURE_BASS_ENGINE and not prof.has_bass_boost: supported = False
        elif fid == FEATURE_GAME_MODE and not prof.has_game_mode: supported = False
        elif fid == FEATURE_IN_EAR and not prof.has_in_ear: supported = False
        elif fid == FEATURE_DUAL_CONNECT and not prof.has_dual_connect: supported = False
        elif fid == FEATURE_VOCAL_ENHANCE and not (prof.has_vocal_enhance or prof.is_open_ear): supported = False

        if supported:
            val = feats.get(str(fid), feats.get(fid, False))
            status = " [ENABLED] " if val else " [DISABLED]"
            print(f"│     • {fname:<28} : {status:<12} │")

    # EQ
    cur_eq = state_dict.get("current_eq", "Balanced")
    print("├────────────────────────────────────────────────────────┤")
    print(f"│  🎵 Sound Master EQ: {cur_eq:<33}│")
    print("└────────────────────────────────────────────────────────┘\n")


async def run_interactive_ipc(client: BudsIPCClient):
    while True:
        state = client.get_state()
        if not state:
            print("❌ Lost connection to menu bar agent.")
            break
        print_status_box(state)

        print("Quick Actions:")
        print("  [1] ANC: Smart Noise Cancellation (Auto)")
        print("  [2] ANC: Transparency Mode")
        print("  [3] ANC: OFF")
        print("  [4] Toggle Game Mode (Ultra-low latency)")
        print("  [5] Toggle Spatial Audio (3D Audio)")
        print("  [6] Toggle BassWave (Bass Boost)")
        print("  [7] Cycle EQ (Balanced / Bass / Clear / Bold)")
        print("  [r] Refresh Status")
        print("  [q] Quit")

        choice = await asyncio.to_thread(input, "\nSelect an option > ")
        choice = choice.strip().lower()

        if choice == '1':
            client.set_noise_mode("Auto")
        elif choice == '2':
            client.set_primary_mode("Transparency")
        elif choice == '3':
            client.set_primary_mode("Off")
        elif choice == '4':
            feats = state.get("features", {})
            cur = feats.get(str(FEATURE_GAME_MODE), False)
            client.set_feature(FEATURE_GAME_MODE, not cur)
        elif choice == '5':
            feats = state.get("features", {})
            cur = feats.get(str(FEATURE_SPATIAL_AUDIO), False)
            client.set_feature(FEATURE_SPATIAL_AUDIO, not cur)
        elif choice == '6':
            feats = state.get("features", {})
            cur = feats.get(str(FEATURE_BASS_ENGINE), False)
            client.set_feature(FEATURE_BASS_ENGINE, not cur)
        elif choice == '7':
            presets = list(EQ_PRESETS.keys())
            cur_eq = state.get("current_eq", "Balanced")
            next_idx = (presets.index(cur_eq) + 1) % len(presets) if cur_eq in presets else 0
            client.set_eq(presets[next_idx])
        elif choice == 'r':
            client.refresh()
        elif choice in ['q', 'exit']:
            break
        else:
            print("Invalid selection.")
        await asyncio.sleep(0.3)


async def run_interactive_standalone(controller: BaseBudsController, transport: BleakTransport):
    while True:
        controller.refresh()
        await asyncio.sleep(0.4)
        print_status_box(controller.state.to_dict())

        print("Quick Actions:")
        print("  [1] ANC: Smart Noise Cancellation (Auto)")
        print("  [2] ANC: Transparency Mode")
        print("  [3] ANC: OFF")
        print("  [4] Toggle Game Mode (Ultra-low latency)")
        print("  [5] Toggle Spatial Audio (3D Audio)")
        print("  [6] Toggle BassWave (Bass Boost)")
        print("  [7] Cycle EQ (Balanced / Bass / Clear / Bold)")
        print("  [r] Refresh Status")
        print("  [q] Quit")

        choice = await asyncio.to_thread(input, "\nSelect an option > ")
        choice = choice.strip().lower()

        if choice == '1':
            controller.set_noise_mode("Auto")
        elif choice == '2':
            controller.set_primary_mode("Transparency")
        elif choice == '3':
            controller.set_primary_mode("Off")
        elif choice == '4':
            cur = controller.state.features.get(FEATURE_GAME_MODE, False)
            controller.set_feature(FEATURE_GAME_MODE, not cur)
        elif choice == '5':
            cur = controller.state.features.get(FEATURE_SPATIAL_AUDIO, False)
            controller.set_feature(FEATURE_SPATIAL_AUDIO, not cur)
        elif choice == '6':
            cur = controller.state.features.get(FEATURE_BASS_ENGINE, False)
            controller.set_feature(FEATURE_BASS_ENGINE, not cur)
        elif choice == '7':
            presets = list(EQ_PRESETS.keys())
            cur_eq = controller.state.current_eq
            next_idx = (presets.index(cur_eq) + 1) % len(presets) if cur_eq in presets else 0
            controller.set_eq(presets[next_idx])
        elif choice == 'r':
            controller.refresh()
        elif choice in ['q', 'exit']:
            break
        else:
            print("Invalid selection.")
        await asyncio.sleep(0.3)


async def main_cli(args):
    if getattr(args, "list_devices", False):
        print_device_catalog()
        return

    # Check if menu bar agent has active session
    if BudsIPCClient.is_server_active() and not getattr(args, "scan", False):
        client = BudsIPCClient()
        if client.connect():
            # Process flags via IPC
            applied_any = False

            if getattr(args, "mode", None) or getattr(args, "level", None):
                target_m = args.mode or args.level
                client.set_noise_mode(target_m)
                applied_any = True

            if getattr(args, "game_mode", None):
                client.set_feature(FEATURE_GAME_MODE, args.game_mode == "on")
                applied_any = True

            if getattr(args, "spatial_audio", None):
                client.set_feature(FEATURE_SPATIAL_AUDIO, args.spatial_audio == "on")
                applied_any = True

            if getattr(args, "bass_boost", None):
                client.set_feature(FEATURE_BASS_ENGINE, args.bass_boost == "on")
                applied_any = True

            if getattr(args, "in_ear", None):
                client.set_feature(FEATURE_IN_EAR, args.in_ear == "on")
                applied_any = True

            if getattr(args, "dual_connect", None):
                client.set_feature(FEATURE_DUAL_CONNECT, args.dual_connect == "on")
                applied_any = True

            if getattr(args, "vocal_enhance", None):
                client.set_feature(FEATURE_VOCAL_ENHANCE, args.vocal_enhance == "on")
                applied_any = True

            if getattr(args, "eq", None):
                client.set_eq(args.eq)
                applied_any = True

            if getattr(args, "interactive", False):
                await run_interactive_ipc(client)
                client.disconnect()
                return

            if applied_any:
                print("✅ Settings applied successfully via active menu bar session.")

            client.refresh()
            await asyncio.sleep(0.2)
            state = client.get_state()
            if state:
                print_status_box(state)
            client.disconnect()
            return

    # Standalone Bleak execution
    controller = BaseBudsController()
    target_addr = getattr(args, "address", None)
    target_name = None

    if not target_addr and not getattr(args, "scan", False):
        target_addr = controller.state.address
        target_name = controller.state.device_name

    transport = BleakTransport(controller, address=target_addr)
    connected = await transport.connect(target_address=target_addr, target_name=target_name)

    if not connected:
        print("❌ Could not connect to earbuds.")
        return

    try:
        applied_any = False

        if getattr(args, "mode", None) or getattr(args, "level", None):
            target_m = args.mode or args.level
            controller.set_noise_mode(target_m)
            applied_any = True

        if getattr(args, "game_mode", None):
            controller.set_feature(FEATURE_GAME_MODE, args.game_mode == "on")
            applied_any = True

        if getattr(args, "spatial_audio", None):
            controller.set_feature(FEATURE_SPATIAL_AUDIO, args.spatial_audio == "on")
            applied_any = True

        if getattr(args, "bass_boost", None):
            controller.set_feature(FEATURE_BASS_ENGINE, args.bass_boost == "on")
            applied_any = True

        if getattr(args, "in_ear", None):
            controller.set_feature(FEATURE_IN_EAR, args.in_ear == "on")
            applied_any = True

        if getattr(args, "dual_connect", None):
            controller.set_feature(FEATURE_DUAL_CONNECT, args.dual_connect == "on")
            applied_any = True

        if getattr(args, "vocal_enhance", None):
            controller.set_feature(FEATURE_VOCAL_ENHANCE, args.vocal_enhance == "on")
            applied_any = True

        if getattr(args, "eq", None):
            controller.set_eq(args.eq)
            applied_any = True

        if getattr(args, "interactive", False):
            await run_interactive_standalone(controller, transport)
            return

        if applied_any:
            print("✅ Settings applied successfully.")

        controller.refresh()
        await asyncio.sleep(0.4)
        print_status_box(controller.state.to_dict())

    finally:
        await transport.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OnePlus Buds Desktop Companion CLI for macOS / Linux / Windows")
    parser.add_argument("command", nargs="?", default="status", help="Subcommand (status, etc.)")
    parser.add_argument("-a", "--address", help="BLE Device UUID or MAC Address (overrides cache)")
    parser.add_argument("-s", "--scan", action="store_true", help="Force BLE scan for nearby earbuds")
    parser.add_argument("-i", "--interactive", action="store_true", help="Launch interactive control menu")
    parser.add_argument("-m", "--mode", choices=["high", "moderate", "low", "auto", "off", "transparency", "mild", "depth", "smart", "anc"], help="Set Noise Control Mode (High / Moderate / Low / Auto / Off / Transparency)")
    parser.add_argument("-l", "--level", choices=["mild", "moderate", "smart"], help="Set ANC Intensity")
    parser.add_argument("--game-mode", choices=["on", "off"], help="Enable/disable Game Mode (low latency)")
    parser.add_argument("--spatial-audio", choices=["on", "off"], help="Enable/disable Spatial Audio (3D sound)")
    parser.add_argument("--bass-boost", choices=["on", "off"], help="Enable/disable BassWave")
    parser.add_argument("--in-ear", choices=["on", "off"], help="Enable/disable In-Ear detection")
    parser.add_argument("--dual-connect", choices=["on", "off"], help="Enable/disable Dual Connection")
    parser.add_argument("--vocal-enhance", choices=["on", "off"], help="Enable/disable Vocal Enhancement")
    parser.add_argument("--eq", choices=["Balanced", "Bass", "Clear", "Bold"], help="Set Equalizer Preset")
    parser.add_argument("--list-devices", action="store_true", help="List all 82 supported OnePlus / OPPO / Realme audio devices across all categories")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    asyncio.run(main_cli(args))


if __name__ == "__main__":
    main()

