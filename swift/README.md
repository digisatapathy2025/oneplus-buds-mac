# OnePlus Buds — Native Swift Edition ⚡

A 100% pure Swift, zero-dependency native implementation of the **OnePlus Buds macOS Companion**, inspired by [`cracked-oneplus-buds`](https://github.com/AasheeshLikePanner/cracked-oneplus-buds.git) but engineered with complete multi-generation hardware protocol support and a native Apple AppKit menu bar UI.

---

## 🚀 Key Differences from `cracked-oneplus-buds`

| Capability | `cracked-oneplus-buds` (`nordbuds.swift`) | OnePlus Buds Native Swift Edition |
| :--- | :--- | :--- |
| **Supported Hardware** | Nord Buds 3 Pro only (`0000079A...`) | **All 82+ OnePlus, OPPO & Realme devices** (both `079A` & `1107` + Fast Pair `FE2C`) |
| **User Interface** | CLI terminal only | **Dual Mode**: Standalone CLI **+** Native AirPods-Style Menu Bar Popover App |
| **Device Switching** | Single device only | **Strict active audio device binding** & dynamic session invalidation |
| **Connection Guard** | Indefinite hangs on offline buds | **5.0-Second connection timeout guard** & targeted open BLE scan |
| **Command Latency** | Hardcoded 10-second sleeps (`asyncAfter`) | **Event-driven packet state machine** (sub-second execution) |
| **Hardware Features** | Basic ANC on/off/trans | **ANC, 4-tier intensity, BassWave™, Game Mode, In-Ear, Spatial Audio & EQ** |
| **Binary Size** | ~114 KB | **~280 KB** (Release Mach-O, zero external dependencies) |
| **RAM Footprint** | ~10 MB | **~12 MB** (vs ~160 MB in Python) |

---

## 📦 What's Included

1. **`nordbuds_plus.swift`**: A drop-in, standalone Swift script that runs directly with `./nordbuds_plus.swift <command>` (zero build step needed).
2. **`buds` (CLI)**: A compiled release binary providing high-speed terminal commands (`buds status`, `buds on`, `buds --game-mode on`, `buds --eq Bold`).
3. **`OnePlusBudsApp`**: A full native macOS status bar application with the AirPods-style frosted glass popover, dynamic capsule battery pills, ANC level sub-selector, and System Settings-style feature switches.

---

## 🛠️ Building & Running

### 1. Run Directly (No Compilation Needed)
```bash
chmod +x nordbuds_plus.swift

./nordbuds_plus.swift on         # Enable Active Noise Cancellation
./nordbuds_plus.swift off        # Turn Noise Cancellation Off
./nordbuds_plus.swift trans      # Enable Transparency Mode
./nordbuds_plus.swift battery    # Query battery levels
./nordbuds_plus.swift game on    # Enable low-latency Game Mode
./nordbuds_plus.swift bass on    # Enable BassWave™
./nordbuds_plus.swift eq Bold    # Set EQ Preset
```

### 2. Build Release Binaries (Swift Package Manager)
```bash
# Build optimized release binaries
swift build -c release

# Run the compiled CLI
.build/release/buds status

# Run the native Menu Bar Application
.build/release/OnePlusBudsApp &
```

---

## 📁 Source Code Architecture

```
swift/
├── Package.swift                    # Swift 6 Package definition
├── nordbuds_plus.swift              # Self-contained runnable CLI script
├── Sources/
│   ├── OnePlusBudsCore/
│   │   ├── Protocol.swift           # OPOv1 TLV framing, packet encoding & decoding
│   │   ├── DeviceCatalog.swift      # 82+ model profiles & GATT service mapping
│   │   ├── BluetoothController.swift# CoreBluetooth state machine & timeout guards
│   │   └── SystemAudioMonitor.swift # IOBluetooth zero-polling device listener
│   ├── OnePlusBudsCLI/
│   │   └── main.swift               # Command-line interface runner
│   └── OnePlusBudsApp/
│       └── main.swift               # AppKit Menu Bar App with AirPods popover
└── README.md
```
