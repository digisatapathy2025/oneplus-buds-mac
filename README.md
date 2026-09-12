# OnePlus Buds macOS Companion 🎧

[![macOS](https://img.shields.io/badge/Platform-macOS%2014%2B%20(Sonoma%20%7C%20Sequoia)-000000?style=for-the-badge&logo=apple&logoColor=white)](https://apple.com)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Architecture](https://img.shields.io/badge/Arch-Apple%20Silicon%20(arm64)%20%7C%20Intel%20(x86__64)-FF8000?style=for-the-badge)](https://apple.com)
[![Devices](https://img.shields.io/badge/Supported%20Devices-82%2B%20Models-E0002A?style=for-the-badge)](./device_manager.py)

A lightweight, native macOS menu bar companion application for **OnePlus**, **OPPO**, and **Realme** wireless earbuds and neckbands. Built on reverse-engineered BES link-layer Bluetooth Low Energy (BLE) protocols from the official HeyMelody app, it brings a seamless, native Apple AirPods-style experience to third-party audio gear on macOS.

---

## ✨ Features at a Glance

### 1. 🎛️ Native AirPods-Style Menu Bar Dropdown
- **Minimalist Menu Bar Item**: Strict icon-only SF Symbol template (`AppKit.NSImageOnly`) with zero text clutter. Hover tooltip provides instant at-a-glance battery percentages.
- **Dynamic 0px Auto-Collapse**: Automatically hides from the menu bar when your earbuds disconnect, eliminating phantom empty spaces or disconnected clutter.
- **Frosted Translucent Popover**: Uses macOS `NSPopover` with blurred background visual effects (`NSVisualEffectMaterialPopover`) and zero frame jumping.
- **AirPods-Style Battery Card**: Dedicated status columns for **Left Earbud**, **Right Earbud**, and **Charging Case** with color-coded capsule pill bars (>20% green, 10–20% orange, <10% red) and charging indicator glyphs (`⚡`).

### 2. 🔇 Comprehensive Noise Control & ANC
- **Primary Modes**: Instant toggling between **Noise Cancellation**, **Off**, and **Transparency**.
- **Adaptive ANC Intensity**: Fine-tune active noise cancellation with a 4-tier sub-selector:
  - `Auto`: Smart adaptive cancellation adjusting to environmental noise.
  - `Low`: Mild cancellation for quiet offices and study rooms.
  - `Moderate`: Medium cancellation for streets and cafes.
  - `High`: Maximum deep cancellation for flights and commutes.

### 3. 🎚️ Hardware Feature Switches
- **BassWave™**: Dynamic algorithmic bass boost enhancement.
- **Game Mode**: Ultra-low audio latency mode for gaming and real-time media.
- **In-Ear Detection**: Automatic playback pause/resume upon earbud removal/insertion.
- **Dual Connection**: Multipoint Bluetooth pairing management across devices.
- **3D Spatial Audio**: Immersive surround sound simulation.
- **Sound Master EQ**: One-click switching between hardware equalizer tunings:
  - `Balanced`
  - `Bass`
  - `Clear`
  - `Bold`

### 4. ⚡ Zero-Polling Background Listener
- **Event-Driven Daemon** (`bluetooth_monitor.py`): Powered by native `IOBluetooth` system notifications.
- **0.0% Idle CPU**: Operates without periodic BLE polling or continuous battery-draining scans.
- **Automatic Wakeup**: Automatically wakes up and connects the moment you take the earbuds out of their charging case.
- **Smart Filtering**: Strictly ignores non-audio Bluetooth peripherals (mice, keyboards, gamepads, trackpads) and unrelated headphones.

### 5. 🔄 Robust Multi-Device Switching & Connection Engine
- **Active Audio Device Synchronization**: Binds CoreBluetooth GATT sessions strictly to the active system audio output device, preventing inactive cached devices from hijacking the connection.
- **State & Handshake Invalidation**: Automatically clears cached BLE addresses and handshake flags whenever you switch between earbuds (e.g. OnePlus Buds 3 ⇄ OnePlus Nord Buds 2).
- **5.0-Second Timeout Guard**: Protects against CoreBluetooth connection hangs if a peripheral goes out of range or fails to respond.
- **Fast Pair & Open BLE Discovery**: Integrates Fast Pair `0xFE2C` service detection and open BLE scanning for earbuds that omit 128-bit service UUIDs from their 31-byte advertisement packets.

### 6. 💻 Terminal CLI & Unix Domain Socket IPC
- Full headless control via command-line arguments:
  ```bash
  # Check live battery and feature status
  python3 buds.py --cli status

  # Change noise cancellation mode
  python3 buds.py --cli -m high

  # Toggle low-latency Game Mode
  python3 buds.py --cli --game-mode on

  # Change EQ preset
  python3 buds.py --cli --eq Balanced
  ```
- **Local IPC Socket** (`/tmp/oneplus_buds_ipc.sock`): Enables communication between the background daemon, the menu bar app, and custom terminal automation scripts.

---

## 🎧 Supported Hardware (82+ Models)

Supports all major OnePlus, OPPO, and Realme wireless audio products across multiple GATT generations (`0000079A...` and `00001107...`):

| Lineup | Popular Supported Models |
| :--- | :--- |
| **OnePlus Buds Pro Series** | Buds Pro 3, Buds Pro 2, Buds Pro 2R, Buds Pro |
| **OnePlus Buds Number Series** | Buds 4, Buds 3, Buds 3V, Buds V, Buds Z2, Buds Z |
| **OnePlus Nord Buds Series** | Nord Buds 4 Pro, Nord Buds 3 Pro, Nord Buds 3, Nord Buds 2, Nord Buds 2r, Nord Buds CE |
| **OnePlus Neckbands** | Bullets Wireless Z2 ANC, Bullets Wireless Z3 |
| **OPPO Enco X Series** | Enco X3, Enco X3s, Enco X3i, Enco X2, Enco X |
| **OPPO Enco Free Series** | Enco Free4, Enco Free3, Enco Free2, Enco Free2i |
| **OPPO Enco Air Series** | Enco Air5 Pro, Enco Air4 Pro, Enco Air3 Pro, Enco Air2 Pro, Enco Air4s, Enco Air3s |
| **OPPO Enco Buds & Clips** | Enco Buds3 Pro, Enco Buds2, Enco Clip, Enco Clip2 |

To see the complete catalog of supported devices directly in your terminal:
```bash
python3 buds.py --list-devices
```

---

## 📁 Architecture Overview

```
├── bluetooth_monitor.py      # Event-driven IOBluetooth system listener daemon
├── buds.py                   # Unified entry point (Menu Bar, CLI, IPC client)
├── buds_app.py               # Standalone runner for the menu bar agent
├── buds_controller.py        # Controller interface for status and configuration
├── core/
│   ├── ble_controller.py     # Base BLE state machine and cache management
│   ├── cli.py                # Command-line interface and formatting
│   ├── ipc.py                # Unix domain socket server and client implementation
│   ├── menubar.py            # Native AppKit menu bar companion (NSPopover UI)
│   ├── protocol.py           # BES TLV packet encoding, decoding & checksum calculation
│   └── transport_bleak.py    # Fallback cross-platform BLE transport
├── device_manager.py         # Multi-model compatibility engine and profile matcher
├── live_device_compatibility_catalog.json # Decrypted HeyMelody model definitions
└── main.c                    # Native C launcher stub for macOS app bundle
```

---

## 🚀 Getting Started

### Prerequisites
- macOS 14.0+ (Sonoma or Sequoia)
- Python 3.11+
- Required Python packages:
  ```bash
  pip3 install pyobjc pyobjc-framework-CoreBluetooth bleak
  ```

### Running the Menu Bar App
```bash
# Launch the native Menu Bar Companion
python3 buds.py --menubar
```

### Background Bluetooth Listener (Optional)
To enable automatic launching when your earbuds connect to macOS, install the LaunchAgent:
```bash
# Start background listener in current session
python3 bluetooth_monitor.py
```

---

## 📄 License
This project is developed for personal and educational use through protocol reverse engineering. All trademarks and brand names are the property of their respective owners.
