# HeyMelody Reverse-Engineering & OnePlus Buds macOS Companion
**Saved Context & Comprehensive Technical Documentation**  
**Dates Active:** September 10 – 13, 2026  
**Target Package:** `com.heytap.headset` (HeyMelody v116.9.0)  
**Hardware Tested:** OnePlus Buds 3 (Model E509A, `063C14`), OnePlus Nord Buds 2 (`062414`), OnePlus Nord Buds CE (`061C14`)  
**Test Environment:** macOS 15+ (Sequoia / Sonoma, Apple Silicon arm64) + Xiaomi 2109119DI (Android 14 via ADB `e2784b6`)

---

## 1. Project Overview & Production Architecture

This project reverse-engineers the proprietary communication protocols between OnePlus / OPPO / Realme earbuds and the official HeyMelody Android application (BES Link Layer over BLE), providing an end-to-end native macOS companion application and an Android feature unlocker.

### 1.1 Production macOS Application Architecture
1. **Single Unified Application**: [`/Applications/OnePlus Buds.app`](file:///Applications/OnePlus%20Buds.app)
   - Standard macOS `.app` bundle configured as an agent (`LSUIElement = true`).
   - Self-contained Mach-O binary (`Contents/MacOS/OnePlusBuds`) linked against macOS `Python.framework` (Python 3.11 C API).
   - Unified entry point:
      - Normal launch (or via Bluetooth trigger): Runs the native Menu Bar companion agent (`core.menubar`) with all controls unified in the native dropdown.

2. **System-Level Bluetooth Audio Listener (Zero Polling)**:
   - Implemented in [`bluetooth_monitor.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/bluetooth_monitor.py).
   - Runs continuously in the background via LaunchAgent `com.oneplus.buds.listener` (0.0% CPU).
   - Listens for system-wide IOBluetooth audio device connection events without active BLE polling or scanning.
   - Strictly ignores non-audio devices (keyboards, mice, gamepads) and unsupported Bluetooth audio devices (AirPods, Sony, Bose, car audio).
   - Resolves device name via SDP profile queries when macOS reports blank names or addresses for newly paired buds.
   - Automatically launches `/Applications/OnePlus Buds.app` or notifies the IPC socket upon connection.

3. **Restored Clean AirPods-Style Popover UI (Fixed 330×540px)**:
   - Native macOS `NSPopover` using `FlippedVisualEffectView` with blurred translucent material (`NSVisualEffectMaterialPopover`, `BehindWindow`).
   - **Zero Frame Shifting**: Completely eliminated dynamic accordion frame resizing and shifting card layouts. Every control has a fixed, static coordinate frame.
   - **Top Header**: AirPods Pro SF Symbol (`airpodspro`), Device Title (`OnePlus Buds 3`), live status indicator (`● Connected` in green / `● Disconnected`), and **Disconnect / Connect** button.
   - **3-Column Battery Card**: Dedicated Left, Right, and Case columns with device SF symbols (`airpod.gen3.left`, `airpod.gen3.right`, `airpodspro.chargingcase.wireless`), live battery percentage (`100% ⚡`), subtitle captions, and mini rounded progress bars (`BatteryPillView`) that dynamically reflect green/orange/red battery health.
   - **Noise Control**: Native rounded `NSSegmentedControl`: `[ Noise Cancelling | Off | Transparency ]`.
   - **ANC Level Sub-Selector**: Fixed-position `NSSegmentedControl`: `[ Auto | Low | Moderate | High ]` (enabled when Noise Cancelling is active; grayed out when Off or Transparency is selected, with zero layout jumping).
   - **Spatial Audio**: Native `NSSegmentedControl`: `[ Off | 3D Spatial Audio ]`.
   - **Audio Enhancements Card**: Native Apple `NSSwitch` toggles for:
     - BassWave™ (Dynamic Bass)
     - Game Mode (Low Latency)
     - In-Ear Auto-Pause Media
     - Dual Device Connection
   - **Sound Master EQ**: Native `NSSegmentedControl`: `[ Balanced | Bass | Clear | Bold ]`.
   - **Footer Bar**: Native push buttons for **Refresh**, **Settings** (opens Desktop GUI), and **Quit**.
   - **Right-Click Context Menu**: Full native macOS `NSMenu` dropdown on right-click or Control-click on the menu bar item.

4. **Local Unix Domain Socket IPC Subsystem**:
   - IPC Socket Path: `/tmp/oneplus_buds_ipc.sock`
   - Server: `BudsIPCServer` in [`core/ipc.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/ipc.py), hosted inside the menu bar agent.
   - Client: `BudsIPCClient` in [`core/ipc.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/ipc.py), used by `buds_controller.py` CLI and `core/gui.py`.
   - Thread-safe command dispatcher supporting:
     - `{"cmd": "status"}`: Returns full connection, model, battery, and noise mode dictionary.
     - `{"cmd": "set_anc", "mode": <mode>}`: Changes noise control mode instantly.
     - `{"cmd": "set_feature", "feature_id": <id>, "enable": <bool>}`: Toggles hardware flags.
     - `{"cmd": "set_eq", "preset": <preset>}`: Sets Sound Master EQ preset.
     - `{"cmd": "device_connected"}` / `{"cmd": "device_disconnected"}`: Signals from background monitor.
     - `{"cmd": "ping"}`: Health check (`{"status": "ok", "message": "pong"}`).
     - State Broadcasting: Automatically broadcasts JSON `state_update` events to all connected clients when settings or battery levels change.

5. **Multi-Device Compatibility Catalog (82+ Models)**:
   - Powered by [`device_manager.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/device_manager.py), [`device_catalog_decrypted.json`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/device_catalog_decrypted.json), and [`live_device_compatibility_catalog.json`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/live_device_compatibility_catalog.json).
   - Supports 82 OnePlus, OPPO, and Realme models (OnePlus Buds 3, Buds Pro 1/2/3, Nord Buds series, Enco X/X2/Free/Air series, Bullets Wireless Z series).
   - Maps model codes, product IDs, feature support flags, and battery layouts (TWS vs. Neckband).

---

## 2. Reverse-Engineered Bluetooth Protocol (BES / OPOv1)

### 2.1 BLE GATT Service & Characteristics
Custom GATT service exposed by the earbuds:
- **Service UUID**: `0000079A-D102-11E1-9B23-00025B00A5A5`
- **TX Characteristic (Write without response / Write)**: `0100079A-D102-11E1-9B23-00025B00A5A5`
- **RX Characteristic (Read / Notify)**: `0200079A-D102-11E1-9B23-00025B00A5A5`
- **Client Characteristic Configuration (CCCD)**: `00002902-0000-1000-8000-00805F9B34FB`
- **Fast Pair Auxiliary Service**: `FE2C123A-8366-4814-8EB0-01DE32100BEA` / `0000079C-D102-11E1-9B23-00025B00A5A5`

### 2.2 OPOv1 Link-Layer Packet Framing
Raw TLV packets must be encapsulated in an **OPOv1 link-layer frame**:
```text
┌──────────────┬──────────────────┬──────────────┬──────────────┬───────────────────────────────┐
│ Magic Header │ Varint Length    │ Control Byte │ Reserved     │ Inner TLV Command Packet      │
│ (1 byte)     │ (1 or 2 bytes)   │ (1 byte)     │ (1 byte)     │ (N bytes)                     │
│ 0xAA         │ len(TLV) + 2     │ 0x00         │ 0x00         │ [Cmd, Seq, Len, Payload...]   │
└──────────────┴──────────────────┴──────────────┴──────────────┴───────────────────────────────┘
```
- **Magic Byte**: `0xAA` (constant).
- **Varint Length**: Length of `(Control + Reserved + TLV)`. Single byte if ≤ 127.
- **Control Byte**: `0x00` indicates an unfragmented packet.

### 2.3 Inner TLV Packet Structure
```text
┌─────────────────┬──────────┬─────────────────┬────────────────────────────┐
│ Command ID      │ Sequence │ Payload Length  │ Payload                    │
│ (2 bytes, LE)   │ (1 byte) │ (2 bytes, LE)   │ (N bytes)                  │
└─────────────────┴──────────┴─────────────────┴────────────────────────────┘
```
Responses have bit 15 set on the Command ID: `Response_Cmd = 0x8000 | Request_Cmd`.

---

## 3. Command Reference & Payload Specifications

### 3.1 Battery Status Query (`0x0106` / `0x8106`)
- **TX Packet**: `AA 07 00 00 06 01 <seq> 00 00`
- **RX Payload (`0x8106`)**:
  - `payload[0]`: Status (`0` = OK)
  - `payload[1]`: Device count (typically 2 or 3)
  - Following pairs: `[DeviceType, RawBattery]`
    - `DeviceType`: `1` = Left Earbud, `2` = Right Earbud, `3` = Charging Case
    - `RawBattery & 0x7F`: Percentage (0–100%)
    - `RawBattery & 0x80`: Charging indicator flag (`⚡`)

### 3.2 Noise Cancellation Control (`0x0404` Set / `0x010C` Query / `0x810C` Response / `0x0204` Notify)
- **Noise Mode Query TX (`0x010C`)**: `AA 09 00 00 0C 01 <seq> 02 00 01 01`
- **Noise Mode Set TX (`0x0404`)**: `AA 0A 00 00 04 04 <seq> 03 00 01 01 <Mode_Mask>`
- **Hardware Command Masks**:
  - `0x01`: Off
  - `0x04`: Transparency Mode *(0x02 is only the parent ANC category in the APK tree; 0x04 is the true hardware command mask for Transparency)*
  - `0x10`: Mild Noise Cancellation
  - `0x20`: Depth / Moderate Noise Cancellation
  - `0x40`: Smart / Dynamic Noise Cancellation

#### Demultiplexed RX State Handling (`0x0204` & `0x810C`)
Queries (`0x810C`) and unsolicited push notifications (`0x0204`) multiplex multiple subsystems:
- If `payload[0] == 0x01`: **Battery Report Packet** (`payload[1]` count, `[dev_type, lvl]` pairs). Must **not** be parsed as noise state.
- If `payload[0] == 0x03`: **Noise Mode State Push Packet**. Active mode mask is at `payload[3] | (payload[4] << 8)`.

#### Hardware Reported State Bitmasks:
- `0x0008` or `0x0001` → **Off**
- `0x0100` or `0x0004` → **Transparency Mode**
- `0x0040` or `0x0080` → **Smart / Personalized Noise Cancellation**
- `0x0020` → **Depth Noise Cancellation**
- `0x0010` → **Mild Noise Cancellation**

### 3.3 Feature Switches (`0x0403` Set / `0x010D` Query)
- **Feature Query TX (`0x010D`)**: `AA 0E 00 00 0D 01 <seq> 07 00 06 05 06 09 11 1B 1D`
- **Feature Set TX (`0x0403`)**: `AA 09 00 00 03 04 <seq> 02 00 <Feature_ID> <0 or 1>`
- **Feature IDs**:
  - `5`: In-Ear Detection (Auto-pause media)
  - `6`: Game Mode (Ultra-low latency audio)
  - `9`: Vocal Enhancement
  - `17` (`0x11`): Dual Connection (Simultaneous multi-device pairing)
  - `27` (`0x1B`): Spatial Audio (3D Virtual Surround)
  - `29` (`0x1D`): BassWave™ (Dynamic Bass Boost)
- **RX Response**: `0x8403` ACK.

### 3.4 Sound Master EQ Presets (`0x0406` / `0x8406`)
- **TX Packet**: `AA 08 00 00 06 04 <seq> 01 00 <Preset_ID>`
- **Preset IDs**:
  - `0`: Balanced
  - `1`: Bass
  - `2`: Clear / Serenade
  - `3`: Bold
- **RX Response**: `0x8406` ACK and `0x0504` state confirmation event.

---

## 4. Key RCA & Technical Implementations (September 10 – 12)

### 4.1 UI Stability & Frame Shifting Elimination (September 12)
- **Problem**: In an attempt to add dynamic accordion sections, collapsible frames with dynamic height resizing caused cards inside the popover to jump and shift vertically whenever toggles or noise modes were clicked.
- **Root Cause**: Custom drawing layers and animated `setFrameSize_` / `setHidden_` calls altered the layout hierarchy dynamically while the popover was active.
- **Solution**: Reverted to the **Original Clean AirPods Popover (Old UI)** with fixed dimensions (`330 × 540 px`). Sub-level controls (`[ Auto | Low | Moderate | High ]`) remain statically positioned and are simply enabled/disabled via AppKit methods without mutating view frames. All elements maintain permanent, fixed coordinates.

### 4.2 Bluetooth Trigger & Zero-Polling Listener (September 11)
- **Problem**: Continuous BLE scanning drained Mac battery and triggered reconnection loops for non-supported Bluetooth audio devices.
- **Solution**: Implemented a system-level IOBluetooth notification listener in `bluetooth_monitor.py` running as LaunchAgent `com.oneplus.buds.listener`. It idles at 0.0% CPU, wakes only on native Bluetooth connection events, validates audio device classes, queries SDP device names, filters against `device_manager.py`, and launches `OnePlus Buds.app` only for verified hardware.

### 4.3 Multi-Frontend Unification & IPC Sync (September 11)
- **Problem**: Code duplication across 4 separate entry points (`buds_app.py`, `buds_gui.py`, `buds_controller.py`, `bluetooth_monitor.py`) each implementing their own BLE stacks and protocol parsers.
- **Solution**: Extracted a modular core:
  - `core/protocol.py`: Single canonical packet encoder/decoder.
  - `core/ble_controller.py`: Shared controller and state machine.
  - `core/ipc.py`: Unix Domain Socket server hosting `/tmp/oneplus_buds_ipc.sock`.
  - `buds.py`: Single launcher routing to menubar, GUI, or CLI.

### 4.4 Demultiplexing Battery & Noise Packets (September 11)
- **Problem**: Battery query responses were overwriting Noise Cancellation states.
- **Solution**: Both query responses (`0x810C`) and unsolicited pushes (`0x0204`) multiplex subsystems into a shared format. If `payload[0] == 0x01`, it is strictly routed to the battery decoder; if `payload[0] == 0x03`, it is routed to the noise state bitmask decoder.

---

## 5. Summary of Files & Locations

| Component | Filesystem Path | Role / Description |
|---|---|---|
| **Production macOS App** | [`/Applications/OnePlus Buds.app`](file:///Applications/OnePlus%20Buds.app) | Unified AppKit agent bundle (`LSUIElement = true`) with embedded Mach-O binary. |
| **Workspace Source Tree** | `/Users/digvijayasatapathy/HeyMelody_unpacked/` | Canonical development source tree. |
| **Git Remote Repository** | [github.com/digisatapathy2025/oneplus-buds-mac](https://github.com/digisatapathy2025/oneplus-buds-mac) | Official GitHub repository for the companion application. |
| **Core Protocol Engine** | [`core/protocol.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/protocol.py) | OPOv1 framing, TLV encoding, battery/noise/feature packet parsing. |
| **BLE Controller & State** | [`core/ble_controller.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/ble_controller.py) | Shared state machine (`BudsState`) and hardware controllers. |
| **Unix Domain Socket IPC** | [`core/ipc.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/ipc.py) | Local socket IPC server (`/tmp/oneplus_buds_ipc.sock`) and client. |
| **Menu Bar Companion** | [`core/menubar.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/core/menubar.py) | Native AppKit status bar agent, icon-only button, 5.0s timeout guard, 0px collapse & AirPods popover. |
| **Scriptable CLI** | [`buds.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/buds.py) | Unified CLI launcher supporting `--cli`, `--menubar`, and status queries. |
| **Bluetooth Audio Daemon** | [`bluetooth_monitor.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/bluetooth_monitor.py) | System-level IOBluetooth audio connection watcher (0.0% CPU). |
| **LaunchAgent Daemon Plist** | `~/Library/LaunchAgents/com.oneplus.buds.listener.plist` | Manages persistent startup of the background Bluetooth listener. |
| **Device Compatibility Catalog** | [`device_manager.py`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/device_manager.py) | Multi-device catalog supporting 82+ OnePlus/OPPO/Realme models. |
| **Live State Cache** | `~/.buds_controller_cache.json` | Persistent cache holding last-known battery, ANC mode, and EQ states. |
| **Native Swift Edition** | [`swift/`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/swift/) | 100% pure Swift 6 implementation (CLI `buds`, Menu Bar App `OnePlusBudsApp`, and `nordbuds_plus.swift`). |
| **Protocol Test Plan & Matrix** | [`heymelody_device_test_plan.xlsx`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/heymelody_device_test_plan.xlsx) | Master Excel workbook containing `Protocol Test Suites` (21 tests) and `Device Test Matrix` (82 models). |
| **Daily Progress (Sept 13)** | [`PROGRESS_2026-09-13.md`](file:///Users/digvijayasatapathy/HeyMelody_unpacked/PROGRESS_2026-09-13.md) | Progress log covering protocol test suites, `collectLogs` catalog audit, and macOS device validations. |

---

## 6. How to Run, Control & Test

### 6.1 Status & Diagnostics via CLI
```bash
# Formatted status box
python3 /Users/digvijayasatapathy/HeyMelody_unpacked/buds.py --cli status

# Native Swift CLI status
/Users/digvijayasatapathy/HeyMelody_unpacked/swift/.build/release/buds status
```

### 6.2 Noise Control via CLI
```bash
# Off
python3 /Users/digvijayasatapathy/HeyMelody_unpacked/buds.py --cli -m off

# Transparency
python3 /Users/digvijayasatapathy/HeyMelody_unpacked/buds.py --cli -m transparency

# Noise Cancellation (High)
python3 /Users/digvijayasatapathy/HeyMelody_unpacked/buds.py --cli -m high
```

### 6.3 Standalone Swift CLI (No Compilation Needed)
```bash
# Run drop-in Swift script
/Users/digvijayasatapathy/HeyMelody_unpacked/swift/nordbuds_plus.swift on
/Users/digvijayasatapathy/HeyMelody_unpacked/swift/nordbuds_plus.swift off
/Users/digvijayasatapathy/HeyMelody_unpacked/swift/nordbuds_plus.swift battery
```

### 6.4 Inspecting Background Daemon Logs
```bash
# Tail background Bluetooth listener logs
tail -f /tmp/oneplus_buds_listener.log

# Check active process status
ps aux | grep -i "OnePlusBuds\|bluetooth_monitor" | grep -v grep
```

### 6.5 Protocol Conformance & Test Suite Execution
```bash
# Verify paired hardware against catalog
python3 -c "import json; cat = json.load(open('device_catalog_decrypted.json'))['compatWhiteList']; print(f'{len(cat)} models loaded')"

# Check Protocol Test Suites in master test plan
python3 -c "import openpyxl; wb = openpyxl.load_workbook('heymelody_device_test_plan.xlsx', data_only=True); print(wb.sheetnames)"
```
