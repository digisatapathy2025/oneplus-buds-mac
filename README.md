# OnePlus Buds macOS Companion 🎧 (Native Swift Edition)

[![macOS](https://img.shields.io/badge/Platform-macOS%2013%2B%20(Ventura%20%7C%20Sonoma%20%7C%20Sequoia)-000000?style=for-the-badge&logo=apple&logoColor=white)](https://apple.com)
[![Swift](https://img.shields.io/badge/Swift-6.0-F05138?style=for-the-badge&logo=swift&logoColor=white)](https://swift.org)
[![Architecture](https://img.shields.io/badge/Arch-Apple%20Silicon%20(arm64)%20%7C%20Intel%20(x86__64)-FF8000?style=for-the-badge)](https://apple.com)
[![Size](https://img.shields.io/badge/Binary%20Size-~380%20KB-brightgreen?style=for-the-badge)](#-installation)
[![Devices](https://img.shields.io/badge/Supported%20Devices-82%2B%20Models-E0002A?style=for-the-badge)](#-supported-hardware-82-models)

A 100% pure Swift, zero-dependency native macOS menu bar companion for **OnePlus**, **OPPO**, and **Realme** wireless earbuds and neckbands. Built on reverse-engineered link-layer Bluetooth Low Energy (BLE) protocols from the official HeyMelody app, it brings a seamless Apple AirPods-style popover and battery card experience to third-party audio gear on macOS.

---

## 📥 Installation

### Option 1: Install via DMG (Recommended)
1. Download the latest `OnePlus Buds-x.x.x.dmg` from the repository releases or build artifacts.
2. Double-click the `.dmg` file to mount it.
3. Drag **OnePlus Buds.app** into your **Applications** folder.
4. Launch **OnePlus Buds** from Applications or Spotlight.

> [!NOTE]
> **First-Time macOS Permission (Gatekeeper & Bluetooth):**
> - When launching for the first time, macOS will request **Bluetooth** permission so the app can connect to your earbuds. Click **Allow**.
> - If macOS displays an unidentified developer warning, open **System Settings > Privacy & Security** and click **Open Anyway**.

---

### Option 2: Build & Package from Source
Requires macOS 13+ and Xcode Command Line Tools (`xcode-select --install`):

```bash
# Clone the repository
git clone https://github.com/digisatapathy2025/oneplus-buds-mac.git
cd oneplus-buds-mac

# Run the automated Swift packaging script
./build_app.sh
```

The script compiles the native Swift binary, ad-hoc codesigns the app bundle, and creates:
- `dist/OnePlus Buds.app` (~380 KB native application bundle)
- `dist/OnePlus Buds-2.1.0.dmg` (~140 KB distributable installer)
- `dist/bin/buds` (optional standalone CLI binary)

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

### 4. ⚡ Zero-Polling Event-Driven Engine
- **Event-Driven**: Powered by native `CoreBluetooth` and `IOBluetooth` system notifications.
- **0.0% Idle CPU & ~12 MB RAM**: Zero background polling or battery drain.
- **Automatic Wakeup**: Automatically connects the moment you open the earbud charging case.
- **Smart Filtering**: Strictly ignores non-audio Bluetooth peripherals (mice, keyboards, gamepads, trackpads) and unrelated headphones.

### 5. 🔄 HeyMelody-Style Multi-Device Switching
- **"My Devices" Switcher**: Native multi-device picker in the popover footer (`Devices ▾`) and right-click context menu, listing all paired OnePlus, OPPO, and Realme earphones on macOS with real-time connection state (`● Connected` / `○ Disconnected`).
- **Hardware Feature Gating**: Automatically adapts the popover controls to match the active device's hardware profile (e.g. gracefully disabling ANC for T2 Non-ANC models like Nord Buds CE).

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

---

## 📄 License
This project is developed for personal and educational use through protocol reverse engineering. All trademarks and brand names are the property of their respective owners.
