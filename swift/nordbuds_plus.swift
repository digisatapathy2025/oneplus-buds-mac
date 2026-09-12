#!/usr/bin/env swift

import Foundation
import CoreBluetooth
import IOBluetooth

let VERSION = "2.0.0 (Multi-Device Swift)"

enum Command {
    case ancOn
    case ancOff
    case transparency
    case battery
    case gameMode(Bool)
    case bass(Bool)
    case eq(String)
    case status
    case help
}

class NordBudsFastCLI: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate, @unchecked Sendable {
    var centralManager: CBCentralManager!
    var peripheral: CBPeripheral?
    var cmdChar: CBCharacteristic?
    var notifyChar: CBCharacteristic?
    var command: Command = .help
    var done = false
    var targetDeviceName: String?

    override init() {
        super.init()
        checkAudioDevice()
        centralManager = CBCentralManager(delegate: self, queue: .main)
    }

    func checkAudioDevice() {
        if let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] {
            for dev in paired {
                if dev.isConnected() {
                    let name = dev.nameOrAddress ?? ""
                    let lower = name.lowercased()
                    if lower.contains("buds") || lower.contains("bullets") || lower.contains("enco") || lower.contains("oneplus") {
                        targetDeviceName = name
                        print("[*] Active Bluetooth Audio Device: \(name)")
                        return
                    }
                }
            }
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            print("[ERROR] Bluetooth is not powered on")
            exit(1)
        }

        // Query both V1 (079A) and V2 (1107) and Fast Pair (FE2C)
        let retrieve = central.retrieveConnectedPeripherals(withServices: [
            CBUUID(string: "0000079A-D102-11E1-9B23-00025B00A5A5"),
            CBUUID(string: "00001107-D102-11E1-9B23-00025B00A5A5"),
            CBUUID(string: "FE2C123A-8366-4814-8EB0-01DE32100BEA"),
            CBUUID(string: "FE2C")
        ])

        if !retrieve.isEmpty {
            var selected = retrieve[0]
            if let target = targetDeviceName?.lowercased() {
                for p in retrieve {
                    let pName = (p.name ?? "").lowercased()
                    if target.contains(pName) || pName.contains(target) {
                        selected = p
                        break
                    }
                }
            }
            self.peripheral = selected
            selected.delegate = self
            print("[*] Fast retrieved: \(selected.name ?? "Buds")")
            central.connect(selected, options: nil)
            return
        }

        print("[*] Scanning for OnePlus / OPPO Buds...")
        centralManager.scanForPeripherals(withServices: nil, options: nil)
    }

    func centralManager(_ central: CBCentralManager,
                        didDiscover peripheral: CBPeripheral,
                        advertisementData: [String : Any],
                        rssi RSSI: NSNumber) {
        let name = peripheral.name ?? (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? ""
        let lower = name.lowercased()
        let target = (targetDeviceName ?? "").lowercased()

        var matched = false
        if !target.isEmpty && (lower.contains(target) || target.contains(lower)) {
            matched = true
        } else if lower.contains("buds") || lower.contains("bullets") || lower.contains("oneplus") || lower.contains("enco") {
            matched = true
        }

        if matched {
            print("[FOUND] \(name) [\(peripheral.identifier.uuidString)]")
            self.peripheral = peripheral
            peripheral.delegate = self
            centralManager.stopScan()
            centralManager.connect(peripheral, options: nil)
        }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        print("[OK] Connected to \(peripheral.name ?? "Earbuds")")
        peripheral.discoverServices([
            CBUUID(string: "0000079A-D102-11E1-9B23-00025B00A5A5"),
            CBUUID(string: "00001107-D102-11E1-9B23-00025B00A5A5"),
            CBUUID(string: "FE2C123A-8366-4814-8EB0-01DE32100BEA"),
            CBUUID(string: "FE2C")
        ])
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        for service in peripheral.services ?? [] {
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        for char in service.characteristics ?? [] {
            let uStr = char.uuid.uuidString.uppercased()
            let props = char.properties.rawValue

            if uStr == "0100079A-D102-11E1-9B23-00025B00A5A5" || uStr == "DB764AC8-4B08-7F25-AAFE-59D03C27BAE3" || (props & 4 != 0 || props & 8 != 0) {
                if cmdChar == nil {
                    cmdChar = char
                    print("[+] Found Write Char: \(uStr)")
                }
            }

            if uStr == "0200079A-D102-11E1-9B23-00025B00A5A5" || uStr == "DB764AC8-4B08-7F25-AAFE-59D03C27BAE4" || (props & 16 != 0 || props & 32 != 0) {
                if notifyChar == nil {
                    notifyChar = char
                    peripheral.setNotifyValue(true, for: char)
                    print("[+] Found Notify Char: \(uStr)")
                }
            }
        }

        if cmdChar != nil && !done {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.startHandshake() }
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard let data = characteristic.value else { return }
        let bytes = [UInt8](data)

        // Parse battery response
        if bytes.count >= 10 && bytes[4] == 0x06 && bytes[5] == 0x81 {
            let count = Int(bytes[7])
            var p = 8
            print("\n========== BATTERY INFO ==========")
            for _ in 0..<count {
                if p + 1 < bytes.count {
                    let dev = bytes[p]
                    let lvl = bytes[p+1] & 0x7F
                    let chg = (bytes[p+1] & 0x80) != 0 ? "⚡" : ""
                    let name = dev == 1 ? "Left Bud" : (dev == 2 ? "Right Bud" : (dev == 3 ? "Case" : "Bud"))
                    print("\(name.padding(toLength: 10, withPad: " ", startingAt: 0)): \(lvl)% \(chg)")
                    p += 2
                }
            }
            print("==================================\n")
            if case .battery = command { exit(0) }
        }
    }

    func sendPacket(_ data: [UInt8], name: String) {
        guard let periph = peripheral, let cmd = cmdChar else { return }
        let hex = data.map { String(format: "%02X", $0) }.joined(separator: " ")
        print("[TX] \(name): \(hex)")
        periph.writeValue(Data(data), for: cmd, type: .withoutResponse)
    }

    func startHandshake() {
        // 1. Hello
        sendPacket([0xAA, 0x07, 0x00, 0x00, 0x00, 0x01, 0x23, 0x00, 0x00, 0x12], name: "HELLO")

        // 2. Register
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            self.sendPacket([0xAA, 0x0C, 0x00, 0x00, 0x00, 0x85, 0x41, 0x05, 0x00, 0x00, 0xB5, 0x50, 0xA0, 0x69], name: "REGISTER")
        }

        // 3. Command execution
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.50) {
            self.executeCommand()
        }
    }

    func executeCommand() {
        guard !done else { return }
        done = true

        switch command {
        case .ancOn:
            sendPacket([0xAA, 0x0A, 0x00, 0x00, 0x04, 0x04, 0x42, 0x03, 0x00, 0x01, 0x01, 0x01], name: "ANC ON")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ ANC Enabled"); exit(0) }

        case .ancOff:
            sendPacket([0xAA, 0x0A, 0x00, 0x00, 0x04, 0x04, 0x40, 0x03, 0x00, 0x01, 0x01, 0x04], name: "ANC OFF")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ ANC Disabled"); exit(0) }

        case .transparency:
            sendPacket([0xAA, 0x0A, 0x00, 0x00, 0x04, 0x04, 0x42, 0x03, 0x00, 0x01, 0x01, 0x02], name: "TRANSPARENCY")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ Transparency Mode Enabled"); exit(0) }

        case .battery:
            sendPacket([0xAA, 0x07, 0x00, 0x00, 0x06, 0x01, 0x25, 0x00, 0x00], name: "BATTERY QUERY")
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { exit(0) }

        case .gameMode(let on):
            let val: UInt8 = on ? 1 : 0
            sendPacket([0xAA, 0x09, 0x00, 0x00, 0x03, 0x04, 0x43, 0x02, 0x00, 0x06, val], name: "GAME MODE \(on ? "ON" : "OFF")")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ Game Mode \(on ? "Enabled" : "Disabled")"); exit(0) }

        case .bass(let on):
            let val: UInt8 = on ? 1 : 0
            sendPacket([0xAA, 0x09, 0x00, 0x00, 0x03, 0x04, 0x44, 0x02, 0x00, 0x1D, val], name: "BASSWAVE \(on ? "ON" : "OFF")")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ BassWave™ \(on ? "Enabled" : "Disabled")"); exit(0) }

        case .eq(let mode):
            let pid: UInt8 = mode.lowercased() == "bass" ? 1 : (mode.lowercased() == "clear" ? 2 : (mode.lowercased() == "bold" ? 3 : 0))
            sendPacket([0xAA, 0x08, 0x00, 0x00, 0x06, 0x04, 0x45, 0x01, 0x00, pid], name: "EQ: \(mode)")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { print("✅ EQ set to \(mode)"); exit(0) }

        case .status:
            sendPacket([0xAA, 0x07, 0x00, 0x00, 0x06, 0x01, 0x25, 0x00, 0x00], name: "BATTERY QUERY")
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { exit(0) }

        case .help:
            printHelp()
            exit(0)
        }
    }
}

func printHelp() {
    print("""
    NordBuds Fast CLI v\(VERSION)
    (Supports OnePlus Buds 3, Buds Pro 3, Nord Buds 2, Bullets Wireless & OPPO Enco)

    Usage: ./nordbuds_plus.swift <command>

    Commands:
      on         - Enable ANC (Active Noise Cancellation)
      off        - Disable ANC
      trans      - Enable Transparency mode
      battery    - Query battery levels
      game <on|off> - Toggle Game Mode
      bass <on|off> - Toggle BassWave
      eq <preset>   - Set EQ (Balanced, Bass, Clear, Bold)
      help       - Show this help message
    """)
}

func main() {
    let args = CommandLine.arguments
    if args.count < 2 {
        printHelp()
        exit(0)
    }

    let cmd = args[1].lowercased()
    var targetCommand: Command = .help

    switch cmd {
    case "on", "anc": targetCommand = .ancOn
    case "off": targetCommand = .ancOff
    case "trans", "transparency": targetCommand = .transparency
    case "battery", "bat": targetCommand = .battery
    case "game":
        let enable = (args.count >= 3 && args[2].lowercased() == "on")
        targetCommand = .gameMode(enable)
    case "bass":
        let enable = (args.count >= 3 && args[2].lowercased() == "on")
        targetCommand = .bass(enable)
    case "eq":
        let preset = args.count >= 3 ? args[2] : "Balanced"
        targetCommand = .eq(preset)
    case "status": targetCommand = .status
    case "help", "--help", "-h":
        printHelp()
        exit(0)
    default:
        print("[ERROR] Unknown command: \(cmd)")
        printHelp()
        exit(1)
    }

    let cli = NordBudsFastCLI()
    cli.command = targetCommand

    DispatchQueue.main.asyncAfter(deadline: .now() + 10.0) {
        if !cli.done {
            print("[ERROR] Timeout - earbuds not responding")
            exit(1)
        }
    }

    RunLoop.main.run()
}

main()
