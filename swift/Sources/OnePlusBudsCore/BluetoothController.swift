import Foundation
import CoreBluetooth
import IOBluetooth

@MainActor
public protocol BluetoothControllerDelegate: AnyObject {
    func controllerStateChanged()
    func logMessage(_ message: String)
}

public final class BluetoothController: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate, @unchecked Sendable {
    public static let shared = BluetoothController()

    public weak var delegate: BluetoothControllerDelegate?
    public let protocolEngine = BudsProtocol()

    // Bluetooth references
    private var centralManager: CBCentralManager!
    public private(set) var peripheral: CBPeripheral?
    private var txChar: CBCharacteristic?
    private var rxChar: CBCharacteristic?

    // State tracking
    public private(set) var isConnected: Bool = false
    public private(set) var isConnecting: Bool = false
    public private(set) var isScanning: Bool = false
    public private(set) var statusMessage: String = "Disconnected"
    public private(set) var activeProfile: DeviceProfile?
    public private(set) var connectedAddress: String?

    public private(set) var battery = BudsBatteryState()
    public private(set) var primaryMode: PrimaryNoiseMode = .off
    public private(set) var ancLevel: AncLevel = .auto
    public private(set) var featureStates: [FeatureId: Bool] = [:]
    public private(set) var currentEq: EqualizerPreset = .balanced

    private var handshakeStarted = false
    private var connectionTimeoutTimer: Timer?
    private var scanTimeoutTimer: Timer?
    private let lock = NSLock()

    override public init() {
        super.init()
        centralManager = CBCentralManager(delegate: self, queue: .main)
    }

    private func log(_ msg: String) {
        let ts = ISO8601DateFormatter().string(from: Date())
        print("[\(ts)] [BudsSwift] \(msg)")
        DispatchQueue.main.async {
            self.delegate?.logMessage(msg)
        }
    }

    private func notifyUI() {
        DispatchQueue.main.async {
            self.delegate?.controllerStateChanged()
        }
    }

    // =========================================================================
    // Connection Timeout Guards
    // =========================================================================
    private func startConnectionTimeout() {
        cancelConnectionTimeout()
        DispatchQueue.main.async {
            self.connectionTimeoutTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { [weak self] _ in
                self?.onConnectionTimeout()
            }
        }
    }

    private func cancelConnectionTimeout() {
        connectionTimeoutTimer?.invalidate()
        connectionTimeoutTimer = nil
    }

    private func onConnectionTimeout() {
        guard isConnecting else { return }
        log("CoreBluetooth connectPeripheral timed out (5.0s). Cancelling.")
        if let periph = peripheral {
            centralManager.cancelPeripheralConnection(periph)
        }
        peripheral = nil
        isConnecting = false
        statusMessage = "Connection Timed Out"
        notifyUI()

        // Retry with targeted open scan if profile is known
        if activeProfile != nil && !isScanning {
            startTargetedScan()
        }
    }

    // =========================================================================
    // CBCentralManagerDelegate
    // =========================================================================
    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        log("CBCentralManager state changed: \(central.state.rawValue)")
        if central.state == .poweredOn {
            if let (profile, _) = SystemAudioMonitor.findConnectedSupportedDevice() {
                self.activeProfile = profile
                self.attemptFastConnect()
            } else {
                log("Bluetooth powered on. No active audio device connected. Idle.")
            }
        }
    }

    public func startTargetedScan() {
        guard centralManager.state == .poweredOn, !isScanning else { return }
        isScanning = true
        log("Starting targeted open BLE scan for: \(activeProfile?.name ?? "supported buds")")
        // Passing nil performs open scan to discover 31-byte adv packets that omit 128-bit UUIDs
        centralManager.scanForPeripherals(withServices: nil, options: nil)

        scanTimeoutTimer?.invalidate()
        scanTimeoutTimer = Timer.scheduledTimer(withTimeInterval: 8.0, repeats: false) { [weak self] _ in
            self?.onScanTimeout()
        }
    }

    private func onScanTimeout() {
        isScanning = false
        scanTimeoutTimer = nil
        if centralManager.isScanning {
            centralManager.stopScan()
            log("Targeted scan timed out (8.0s).")
        }
        if isConnecting {
            isConnecting = false
            statusMessage = "Disconnected"
            notifyUI()
        }
    }

    public func attemptFastConnect() {
        guard !isConnected, !isConnecting, centralManager.state == .poweredOn else { return }
        handshakeStarted = false

        // Synchronize strictly with connected audio device
        if let (activeProf, _) = SystemAudioMonitor.findConnectedSupportedDevice() {
            if self.activeProfile?.name != activeProf.name {
                log("Active audio device changed to '\(activeProf.name)'. Resetting session.")
                connectedAddress = nil
                handshakeStarted = false
            }
            self.activeProfile = activeProf
        }

        guard let targetProfile = activeProfile else {
            log("No active supported Bluetooth audio device connected. Aborting connect.")
            return
        }

        let targetName = targetProfile.name.trimmingCharacters(in: .whitespaces).lowercased()

        // 1. Zero-delay retrieve of connected peripherals by service UUIDs
        var servicesToQuery: [CBUUID] = [
            CBUUID(string: BudsUUIDs.serviceV1),
            CBUUID(string: BudsUUIDs.serviceV2),
            CBUUID(string: BudsUUIDs.fastPairService),
            CBUUID(string: BudsUUIDs.fastPairShort)
        ]
        if let customUUID = CBUUID(string: targetProfile.serviceUUID) as CBUUID?, !servicesToQuery.contains(customUUID) {
            servicesToQuery.append(customUUID)
        }

        let connectedPeriphs = centralManager.retrieveConnectedPeripherals(withServices: servicesToQuery)
        var targetPeriph: CBPeripheral?

        for p in connectedPeriphs {
            let pName = (p.name ?? "").trimmingCharacters(in: .whitespaces).lowercased()
            if targetName.contains(pName) || pName.contains(targetName) {
                targetPeriph = p
                break
            } else if let matched = DeviceCatalog.shared.matchDevice(name: pName), matched.name.lowercased() == targetName {
                targetPeriph = p
                break
            }
        }

        if let p = targetPeriph {
            log("Fast retrieved connected peripheral: \(p.name ?? "") [\(p.identifier.uuidString)]")
            self.isConnecting = true
            self.statusMessage = "Connecting..."
            self.peripheral = p
            p.delegate = self
            self.connectedAddress = p.identifier.uuidString
            self.handshakeStarted = false
            self.centralManager.connect(p, options: nil)
            self.startConnectionTimeout()
            self.notifyUI()
            return
        }

        // 2. Open targeted BLE scan
        startTargetedScan()
    }

    public func centralManager(_ central: CBCentralManager,
                               didDiscover peripheral: CBPeripheral,
                               advertisementData: [String : Any],
                               rssi RSSI: NSNumber) {
        var name = peripheral.name ?? ""
        if name.isEmpty, let localName = advertisementData[CBAdvertisementDataLocalNameKey] as? String {
            name = localName
        }
        name = name.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }

        let nameLower = name.lowercased()
        let targetName = (activeProfile?.name ?? "").trimmingCharacters(in: .whitespaces).lowercased()

        var matchedProfile: DeviceProfile?
        if !targetName.isEmpty && (nameLower.contains(targetName) || targetName.contains(nameLower)) {
            matchedProfile = activeProfile
        } else if let cand = DeviceCatalog.shared.matchDevice(name: name) {
            if let active = activeProfile, cand.name.lowercased() == active.name.lowercased() {
                matchedProfile = active
            } else if activeProfile == nil {
                matchedProfile = cand
            }
        }

        if let prof = matchedProfile {
            log("Discovered matching BLE peripheral: \(name) [\(peripheral.identifier.uuidString)]")
            isScanning = false
            centralManager.stopScan()
            scanTimeoutTimer?.invalidate()
            scanTimeoutTimer = nil

            self.isConnecting = true
            self.statusMessage = "Connecting..."
            self.peripheral = peripheral
            self.activeProfile = prof
            self.connectedAddress = peripheral.identifier.uuidString
            peripheral.delegate = self
            self.handshakeStarted = false
            centralManager.connect(peripheral, options: nil)
            startConnectionTimeout()
            notifyUI()
        }
    }

    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        cancelConnectionTimeout()
        isConnected = true
        isConnecting = false
        statusMessage = "Connected"
        handshakeStarted = false

        if let pName = peripheral.name, let matched = DeviceCatalog.shared.matchDevice(name: pName) {
            self.activeProfile = matched
        }
        log("CoreBluetooth Connected to \(peripheral.name ?? "Buds") [\(peripheral.identifier.uuidString)]")
        notifyUI()

        let servicesToDiscover: [CBUUID] = [
            CBUUID(string: BudsUUIDs.serviceV1),
            CBUUID(string: BudsUUIDs.serviceV2),
            CBUUID(string: BudsUUIDs.fastPairService),
            CBUUID(string: BudsUUIDs.fastPairShort)
        ]
        peripheral.discoverServices(servicesToDiscover)
    }

    public func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        cancelConnectionTimeout()
        isConnected = false
        isConnecting = false
        self.peripheral = nil
        handshakeStarted = false
        connectedAddress = nil
        statusMessage = "Connection Failed"
        log("CoreBluetooth failed to connect: \(error?.localizedDescription ?? "unknown error")")
        notifyUI()
    }

    public func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        cancelConnectionTimeout()
        isConnected = false
        isConnecting = false
        self.peripheral = nil
        self.txChar = nil
        self.rxChar = nil
        handshakeStarted = false
        connectedAddress = nil
        statusMessage = "Disconnected"
        battery = BudsBatteryState()
        log("CoreBluetooth Disconnected from peripheral: \(error?.localizedDescription ?? "clean disconnect")")
        notifyUI()
    }

    // =========================================================================
    // CBPeripheralDelegate
    // =========================================================================
    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let services = peripheral.services else { return }
        for s in services {
            peripheral.discoverCharacteristics(nil, for: s)
        }
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let chars = service.characteristics else { return }
        for c in chars {
            let uStr = c.uuid.uuidString.uppercased()
            let props = c.properties.rawValue

            // RX Characteristic (Notify)
            if uStr == BudsUUIDs.rxCharV1.uppercased() || uStr == BudsUUIDs.rxCharLegacy.uppercased() ||
               ((service.uuid.uuidString == BudsUUIDs.serviceV1 || service.uuid.uuidString == BudsUUIDs.serviceV2) && (props & 16 != 0 || props & 32 != 0)) {
                if rxChar == nil {
                    rxChar = c
                    peripheral.setNotifyValue(true, for: c)
                    log("Bound RX Characteristic: \(uStr)")
                }
            }

            // TX Characteristic (Write Without Response)
            if uStr == BudsUUIDs.txCharV1.uppercased() || uStr == BudsUUIDs.txCharLegacy.uppercased() ||
               ((service.uuid.uuidString == BudsUUIDs.serviceV1 || service.uuid.uuidString == BudsUUIDs.serviceV2) && (props & 4 != 0 || props & 8 != 0)) {
                if txChar == nil {
                    txChar = c
                    log("Bound TX Characteristic: \(uStr)")
                }
            }

            // Fast Pair auxiliary telemetry
            if service.uuid.uuidString == BudsUUIDs.fastPairService || service.uuid.uuidString == BudsUUIDs.fastPairShort {
                if props & 16 != 0 || props & 32 != 0 {
                    peripheral.setNotifyValue(true, for: c)
                }
            }
        }

        if txChar != nil && !handshakeStarted {
            handshakeStarted = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
                self?.sendHello()
            }
        }
    }

    public func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let data = characteristic.value, !data.isEmpty else { return }
        let bytes = [UInt8](data)
        parseNotification(bytes)
    }

    // =========================================================================
    // Handshake & Packet Dispatcher
    // =========================================================================
    public func sendBytes(_ bytes: [UInt8]) -> Bool {
        guard let periph = peripheral, let tx = txChar else { return false }
        periph.writeValue(Data(bytes), for: tx, type: .withoutResponse)
        return true
    }

    private func sendHello() {
        guard peripheral != nil && txChar != nil else { return }
        _ = sendBytes(protocolEngine.buildHello())
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.sendRegister()
        }
    }

    private func sendRegister() {
        guard peripheral != nil && txChar != nil else { return }
        _ = sendBytes(protocolEngine.buildRegister())
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.30) { [weak self] in
            self?.sendInitialQueries()
        }
    }

    private func sendInitialQueries() {
        guard peripheral != nil && txChar != nil else { return }
        _ = sendBytes(protocolEngine.buildBatteryQuery())
        _ = sendBytes(protocolEngine.buildNoiseQuery())
        let featureIds: [UInt8] = [
            FeatureId.inEar.rawValue,
            FeatureId.gameMode.rawValue,
            FeatureId.vocalEnhance.rawValue,
            FeatureId.dualConnect.rawValue,
            FeatureId.spatialAudio.rawValue,
            FeatureId.bassEngine.rawValue
        ]
        _ = sendBytes(protocolEngine.buildFeatureQuery(featureIds: featureIds))
    }

    // =========================================================================
    // Response Parser
    // =========================================================================
    private func parseNotification(_ rawBytes: [UInt8]) {
        guard let (cmdId, _, payload) = BudsProtocol.parseTLVPacket(rawBytes) else { return }

        switch cmdId {
        case 0x8106: // Battery Response
            let parsed = BudsProtocol.parseBatteryPayload(payload, isNeckband: activeProfile?.isNeckband ?? false)
            self.battery = parsed
            notifyUI()

        case 0x8404, 0x810C: // Noise Mode Response
            if payload.count >= 2 {
                let mask = UInt16(payload[0]) | (UInt16(payload[1]) << 8)
                let decoded = BudsProtocol.decodeNoiseMode(mask: mask, lastAncMode: self.ancLevel)
                self.primaryMode = decoded.primary
                self.ancLevel = decoded.level
                notifyUI()
            }

        case 0x810D, 0x8403: // Feature Response
            if payload.count >= 2 {
                var pIdx = 1
                while pIdx + 1 < payload.count {
                    let fIdRaw = payload[pIdx]
                    let val = payload[pIdx + 1] != 0
                    if let fId = FeatureId(rawValue: fIdRaw) {
                        self.featureStates[fId] = val
                    }
                    pIdx += 2
                }
                notifyUI()
            }

        case 0x8205, 0x8406, 0x0504: // Equalizer Response
            if !payload.isEmpty {
                self.currentEq = EqualizerPreset.from(rawId: payload[0])
                notifyUI()
            }

        default:
            break
        }
    }

    // =========================================================================
    // Public User Actions
    // =========================================================================
    public func setNoiseMode(primary: PrimaryNoiseMode, level: AncLevel? = nil) {
        self.primaryMode = primary
        if let lvl = level {
            self.ancLevel = lvl
        }
        var mask: UInt8 = 0x01
        switch primary {
        case .noiseCancellation:
            mask = self.ancLevel.hardwareMask
        case .off:
            mask = 0x01
        case .transparency:
            mask = 0x04
        }
        _ = sendBytes(protocolEngine.buildNoiseControl(modeMask: mask))
        notifyUI()
    }

    public func setFeature(_ feature: FeatureId, enabled: Bool) {
        featureStates[feature] = enabled
        _ = sendBytes(protocolEngine.buildFeatureSet(featureId: feature.rawValue, enable: enabled))
        notifyUI()
    }

    public func setEqualizer(_ preset: EqualizerPreset) {
        self.currentEq = preset
        _ = sendBytes(protocolEngine.buildEqSet(presetId: preset.rawId))
        notifyUI()
    }

    public func refresh() {
        sendInitialQueries()
    }

    public func disconnect() {
        cancelConnectionTimeout()
        handshakeStarted = false
        connectedAddress = nil
        if let periph = peripheral {
            centralManager.cancelPeripheralConnection(periph)
        }
    }
}
