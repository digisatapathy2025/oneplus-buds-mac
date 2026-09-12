import Foundation
import OnePlusBudsCore

@MainActor
final class CLIRunner: BluetoothControllerDelegate {
    let controller = BluetoothController.shared
    var targetAction: (() -> Void)?
    var isDone = false

    init() {
        controller.delegate = self
    }

    func controllerStateChanged() {
        if controller.isConnected && !isDone {
            if let action = targetAction {
                targetAction = nil
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    action()
                }
            }
        }
    }

    func logMessage(_ message: String) {
        // Suppress verbose logs in CLI unless debug
    }

    func finish() {
        isDone = true
        exit(0)
    }
}

func printHelp() {
    print("""
    OnePlus Buds macOS CLI (Native Swift Edition)

    Usage: buds <command> [options]

    Commands:
      status                    Show live connection, battery, and noise mode
      on | anc                  Enable Active Noise Cancellation
      off                       Turn Noise Cancellation Off
      trans | transparency      Enable Transparency Mode
      battery | bat             Print Left, Right, and Case battery levels
      --game-mode <on|off>      Toggle ultra-low latency Game Mode
      --bass <on|off>           Toggle BassWave™ algorithmic bass boost
      --in-ear <on|off>         Toggle In-Ear wear detection auto-pause
      --spatial <on|off>        Toggle 3D Spatial Audio
      --dual <on|off>           Toggle Dual Device Connection
      --eq <preset>             Set EQ: Balanced, Bass, Clear, Bold
      --list                    List supported models (82+ devices)
      help                      Show this help message

    Examples:
      buds status
      buds on
      buds trans
      buds --game-mode on
      buds --eq Bold
    """)
}

func printStatusBox(controller: BluetoothController) {
    let profName = controller.activeProfile?.name ?? "OnePlus Earbuds"
    let leftLvl = controller.battery.left.isConnected ? "\(controller.battery.left.level)%" : "--%"
    let rightLvl = controller.battery.right.isConnected ? "\(controller.battery.right.level)%" : "--%"
    let caseLvl = controller.battery.caseBattery.isConnected ? "\(controller.battery.caseBattery.level)%" : "--%"
    let leftBolt = controller.battery.left.isCharging ? "⚡" : " "
    let rightBolt = controller.battery.right.isCharging ? "⚡" : " "
    let caseBolt = controller.battery.caseBattery.isCharging ? "⚡" : " "

    let gameMode = controller.featureStates[.gameMode] == true ? "[ENABLED]" : "[DISABLED]"
    let bassWave = controller.featureStates[.bassEngine] == true ? "[ENABLED]" : "[DISABLED]"
    let inEar = controller.featureStates[.inEar] == true ? "[ENABLED]" : "[DISABLED]"

    print("""

    ┌────────────────────────────────────────────────────────┐
    │  \(profName.padding(toLength: 52, withPad: " ", startingAt: 0))│
    ├────────────────────────────────────────────────────────┤
    │  🔋 Battery:                                           │
    │     • Left Earbud : \(leftLvl) \(leftBolt)          Right Earbud: \(rightLvl) \(rightBolt)      │
    │     • Case        : \(caseLvl) \(caseBolt)                                    │
    ├────────────────────────────────────────────────────────┤
    │  🎧 Noise Control: \(controller.primaryMode.rawValue.uppercased().padding(toLength: 35, withPad: " ", startingAt: 0))│
    ├────────────────────────────────────────────────────────┤
    │  🎛️  Feature Switches:                                  │
    │     • Game Mode (Low Latency)      :  \(gameMode)    │
    │     • BassWave™ (Bass Boost)       :  \(bassWave)    │
    │     • In-Ear Detection             :  \(inEar)    │
    ├────────────────────────────────────────────────────────┤
    │  🎵 Sound Master EQ: \(controller.currentEq.rawValue.padding(toLength: 34, withPad: " ", startingAt: 0))│
    └────────────────────────────────────────────────────────┘

    """)
}

@MainActor
func main() {
    let args = CommandLine.arguments

    if args.count < 2 || args.contains("-h") || args.contains("--help") || args.contains("help") {
        printHelp()
        exit(0)
    }

    if args.contains("--list") {
        print("\nSupported Devices Catalog (82+ Models across OnePlus / OPPO / Realme):")
        for p in DeviceCatalog.shared.profiles {
            let type = p.isNeckband ? "Neckband" : "TWS Earbuds"
            print("  • \(p.name.padding(toLength: 34, withPad: " ", startingAt: 0)) [\(p.modelCode)] (\(type))")
        }
        print()
        exit(0)
    }

    let runner = CLIRunner()
    let cmd = args[1].lowercased()

    switch cmd {
    case "status":
        runner.targetAction = {
            runner.controller.refresh()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                printStatusBox(controller: runner.controller)
                runner.finish()
            }
        }

    case "on", "anc":
        runner.targetAction = {
            print("[*] Setting Noise Cancellation to ON...")
            runner.controller.setNoiseMode(primary: .noiseCancellation, level: .auto)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                print("✅ Noise Cancellation Enabled.")
                runner.finish()
            }
        }

    case "off":
        runner.targetAction = {
            print("[*] Turning Noise Cancellation OFF...")
            runner.controller.setNoiseMode(primary: .off)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                print("✅ Noise Cancellation Turned Off.")
                runner.finish()
            }
        }

    case "trans", "transparency":
        runner.targetAction = {
            print("[*] Setting Transparency Mode...")
            runner.controller.setNoiseMode(primary: .transparency)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                print("✅ Transparency Mode Enabled.")
                runner.finish()
            }
        }

    case "battery", "bat":
        runner.targetAction = {
            runner.controller.refresh()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                let b = runner.controller.battery
                print("\n========== BATTERY STATUS ==========")
                if b.left.isConnected { print("Left Bud:  \(b.left.level)% \(b.left.isCharging ? "⚡" : "")") }
                if b.right.isConnected { print("Right Bud: \(b.right.level)% \(b.right.isCharging ? "⚡" : "")") }
                if b.caseBattery.isConnected { print("Case:      \(b.caseBattery.level)% \(b.caseBattery.isCharging ? "⚡" : "")") }
                if b.single.isConnected { print("Bud:       \(b.single.level)% \(b.single.isCharging ? "⚡" : "")") }
                print("====================================\n")
                runner.finish()
            }
        }

    case "--game-mode":
        guard args.count >= 3 else { print("Usage: --game-mode <on|off>"); exit(1) }
        let enable = (args[2].lowercased() == "on")
        runner.targetAction = {
            runner.controller.setFeature(.gameMode, enabled: enable)
            print("✅ Game Mode \(enable ? "Enabled" : "Disabled").")
            runner.finish()
        }

    case "--bass", "--bass-boost":
        guard args.count >= 3 else { print("Usage: --bass <on|off>"); exit(1) }
        let enable = (args[2].lowercased() == "on")
        runner.targetAction = {
            runner.controller.setFeature(.bassEngine, enabled: enable)
            print("✅ BassWave™ \(enable ? "Enabled" : "Disabled").")
            runner.finish()
        }

    case "--in-ear":
        guard args.count >= 3 else { print("Usage: --in-ear <on|off>"); exit(1) }
        let enable = (args[2].lowercased() == "on")
        runner.targetAction = {
            runner.controller.setFeature(.inEar, enabled: enable)
            print("✅ In-Ear Detection \(enable ? "Enabled" : "Disabled").")
            runner.finish()
        }

    case "--eq":
        guard args.count >= 3 else { print("Usage: --eq <Balanced|Bass|Clear|Bold>"); exit(1) }
        let val = args[2].capitalized
        if let preset = EqualizerPreset.allCases.first(where: { $0.rawValue.lowercased() == val.lowercased() }) {
            runner.targetAction = {
                runner.controller.setEqualizer(preset)
                print("✅ Sound Master EQ set to \(preset.rawValue).")
                runner.finish()
            }
        } else {
            print("Unknown EQ preset. Options: Balanced, Bass, Clear, Bold")
            exit(1)
        }

    default:
        print("[ERROR] Unknown command: \(cmd)")
        printHelp()
        exit(1)
    }

    print("[*] Connecting to OnePlus / OPPO earbuds...")
    runner.controller.attemptFastConnect()

    // Safety timeout for CLI execution
    DispatchQueue.main.asyncAfter(deadline: .now() + 10.0) {
        if !runner.isDone {
            print("[ERROR] Connection timed out. Make sure your earbuds are connected to Mac Bluetooth.")
            exit(1)
        }
    }

    RunLoop.main.run()
}

main()
