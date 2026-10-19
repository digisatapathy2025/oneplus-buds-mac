import Foundation
@preconcurrency import IOBluetooth

public struct PairedBudsDevice: Sendable, Equatable {
    public let name: String
    public let address: String
    public let isConnected: Bool
    public let profile: DeviceProfile

    public init(name: String, address: String, isConnected: Bool, profile: DeviceProfile) {
        self.name = name
        self.address = address
        self.isConnected = isConnected
        self.profile = profile
    }
}

@MainActor
public protocol SystemAudioMonitorDelegate: AnyObject {
    func audioDeviceConnected(name: String, profile: DeviceProfile)
    func audioDeviceDisconnected(name: String, profile: DeviceProfile)
}

@MainActor
public final class SystemAudioMonitor: NSObject {
    public weak var delegate: SystemAudioMonitorDelegate?
    private var isRunning = false

    // Native IOBluetooth notification tokens
    private var connectNotification: IOBluetoothUserNotification?
    private var disconnectNotifications: [String: IOBluetoothUserNotification] = [:]

    // Tracked connected devices keyed by normalized address (e.g. "88:92:CC:43:31:19")
    private var connectedDevices: [String: (device: IOBluetoothDevice, profile: DeviceProfile, name: String)] = [:]

    // In-flight delayed retry addresses to prevent overlapping checks
    private var pendingRetries: Set<String> = []

    override public init() {
        super.init()
    }

    deinit {
        connectNotification?.unregister()
        for (_, notif) in disconnectNotifications {
            notif.unregister()
        }
    }

    private func log(_ msg: String) {
        let ts = ISO8601DateFormatter().string(from: Date())
        print("[\(ts)] \(msg)")
    }

    // =========================================================================
    // Bluetooth Audio Device Classification
    // =========================================================================
    nonisolated private static let nonAudioKeywords: [String] = [
        "mouse", "keyboard", "trackpad", "keypad", "remote", "pencil", "controller"
    ]

    nonisolated private static let audioKeywords: [String] = [
        "buds", "headphones", "headset", "earphones", "earbuds", "audio",
        "speaker", "sound", "enco", "bullets", "airpods", "tws", "wireless stereo"
    ]

    nonisolated public static func isBluetoothAudioDevice(_ device: IOBluetoothDevice) -> Bool {
        let name = (device.name ?? device.nameOrAddress ?? "").lowercased()

        // 1. DeviceCatalog match is definitive positive evidence
        if DeviceCatalog.shared.matchDevice(name: name) != nil {
            return true
        }

        // 2. Negative rejection for obvious non-audio peripherals
        for keyword in nonAudioKeywords {
            if name.contains(keyword) {
                return false
            }
        }

        let cod = device.classOfDevice
        let majorDeviceClass = (cod >> 8) & 0x1F
        let audioServiceBit = (cod & 0x200000) != 0       // Bit 21: Audio service
        let renderingBit    = (cod & 0x040000) != 0       // Bit 18: Rendering (Speaker/Headphones)
        let capturingBit    = (cod & 0x080000) != 0       // Bit 19: Capturing (Microphone)

        // 3. Native CoD audio evidence
        if majorDeviceClass == 0x04 || audioServiceBit || renderingBit || capturingBit {
            return true
        }

        // 4. SDP profile services evidence
        if let services = device.services as? [IOBluetoothSDPServiceRecord] {
            for svc in services {
                if let sName = svc.getServiceName()?.lowercased() {
                    if sName.contains("audio") || sName.contains("headset") ||
                       sName.contains("handsfree") || sName.contains("a2dp") ||
                       sName.contains("avrcp") || sName.contains("sound") ||
                       sName.contains("oppointeraction") || sName.contains("commonspp") {
                        return true
                    }
                }
            }
        }

        // 5. Audio name heuristics
        for keyword in audioKeywords {
            if name.contains(keyword) {
                return true
            }
        }

        // 6. Explicit rejection for non-audio major classes when no audio evidence exists
        if cod != 0 && (majorDeviceClass == 0x01 || majorDeviceClass == 0x02 || majorDeviceClass == 0x05) {
            return false
        }

        return false
    }

    nonisolated public static func findConnectedSupportedDevice() -> (profile: DeviceProfile, device: IOBluetoothDevice)? {
        guard let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] else {
            return nil
        }
        for dev in paired {
            if dev.isConnected() && isBluetoothAudioDevice(dev) {
                let name = dev.name ?? dev.nameOrAddress ?? ""
                if let profile = DeviceCatalog.shared.matchDevice(name: name) {
                    return (profile, dev)
                }
            }
        }
        return nil
    }

    nonisolated public static func getPairedSupportedDevices() -> [(device: IOBluetoothDevice, profile: DeviceProfile, isConnected: Bool)] {
        guard let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] else {
            return []
        }
        var seen = Set<String>()
        var results: [(device: IOBluetoothDevice, profile: DeviceProfile, isConnected: Bool)] = []

        for dev in paired {
            let addr = (dev.addressString ?? dev.nameOrAddress ?? "").replacingOccurrences(of: "-", with: ":").uppercased()
            if addr.isEmpty || seen.contains(addr) { continue }

            let rawName = (dev.name ?? dev.nameOrAddress ?? "").trimmingCharacters(in: .whitespaces)
            if let profile = DeviceCatalog.shared.matchDevice(name: rawName) {
                seen.insert(addr)
                let isConn = dev.isConnected()
                results.append((device: dev, profile: profile, isConnected: isConn))
            }
        }
        return results
    }

    // =========================================================================
    // Monitor Lifecycle (Zero Polling, Event-Driven)
    // =========================================================================
    public func start() {
        guard !isRunning else { return }
        isRunning = true

        // Register for native IOBluetooth device connection notifications
        connectNotification = IOBluetoothDevice.register(
            forConnectNotifications: self,
            selector: #selector(deviceConnected(notification:device:))
        )

        // One-time inspection of currently connected devices at launch
        if let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] {
            for dev in paired {
                if dev.isConnected() {
                    let addr = dev.addressString ?? dev.nameOrAddress ?? ""
                    processConnectedDevice(dev, address: addr, retryCount: 0)
                }
            }
        }
    }

    public func stop() {
        guard isRunning else { return }
        isRunning = false

        connectNotification?.unregister()
        connectNotification = nil

        for (_, notif) in disconnectNotifications {
            notif.unregister()
        }
        disconnectNotifications.removeAll()
        connectedDevices.removeAll()
        pendingRetries.removeAll()
    }

    // =========================================================================
    // IOBluetooth Native Notifications
    // =========================================================================
    @objc nonisolated private func deviceConnected(notification: IOBluetoothUserNotification, device: IOBluetoothDevice) {
        let addr = device.addressString ?? device.nameOrAddress ?? "unknown"
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            guard let dev = IOBluetoothDevice(addressString: addr) ?? (IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice])?.first(where: { $0.addressString == addr }) else {
                return
            }
            self.processConnectedDevice(dev, address: addr, retryCount: 0)
        }
    }

    @objc nonisolated private func deviceDisconnected(notification: IOBluetoothUserNotification, device: IOBluetoothDevice) {
        let addr = device.addressString ?? device.nameOrAddress ?? "unknown"
        Task { @MainActor [weak self] in
            self?.processDisconnectedDevice(address: addr)
        }
    }

    // =========================================================================
    // Processing & Classification Pipeline
    // =========================================================================
    private func normalizeAddress(_ addr: String) -> String {
        return addr.replacingOccurrences(of: "-", with: ":").uppercased()
    }

    private func isAddressLike(_ str: String) -> Bool {
        let stripped = str.replacingOccurrences(of: ":", with: "").replacingOccurrences(of: "-", with: "")
        return stripped.count == 12 && stripped.allSatisfy { $0.isHexDigit }
    }

    private func processConnectedDevice(_ device: IOBluetoothDevice, address: String, retryCount: Int) {
        guard isRunning else { return }

        let normAddress = normalizeAddress(address)

        // Deduplication: prevent duplicate connection callbacks for the same physical device
        if connectedDevices[normAddress] != nil {
            return
        }

        let rawName = (device.name ?? "").trimmingCharacters(in: .whitespaces)
        let isNameUnresolved = rawName.isEmpty || isAddressLike(rawName)

        // Name resolution race: if name is empty or address-like, schedule bounded delayed check (max 3)
        if isNameUnresolved && retryCount < 3 {
            let delay = (retryCount == 0) ? 0.5 : ((retryCount == 1) ? 1.0 : 1.5)
            pendingRetries.insert(normAddress)
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self = self else { return }
                self.pendingRetries.remove(normAddress)
                guard let dev = IOBluetoothDevice(addressString: address) ?? (device.isConnected() ? device : nil) else { return }
                self.processConnectedDevice(dev, address: address, retryCount: retryCount + 1)
            }
            return
        }

        let resolvedName = rawName.isEmpty ? (device.nameOrAddress ?? normAddress) : rawName

        // Gather diagnostic telemetry for mandatory stage logging
        let cod = device.classOfDevice
        let majorDeviceClass = (cod >> 8) & 0x1F
        let audioServiceBit = (cod & 0x200000) != 0
        let renderingBit = (cod & 0x040000) != 0
        let capturingBit = (cod & 0x080000) != 0

        var serviceNames: [String] = []
        if let sRecords = device.services as? [IOBluetoothSDPServiceRecord] {
            serviceNames = sRecords.compactMap { $0.getServiceName() }
        }

        let catalogMatch = DeviceCatalog.shared.matchDevice(name: resolvedName)
        let isAudio = Self.isBluetoothAudioDevice(device)
        let isSupported = isAudio && (catalogMatch != nil)

        // Mandatory Diagnostic Logging for Every Event
        log("[BT] Device connected: \(resolvedName) / \(normAddress)")
        log("[BT] Class of Device: 0x\(String(format: "%06X", cod))")
        log("[BT] Major Device Class: 0x\(String(format: "%02X", majorDeviceClass))")
        log("[BT] Audio service bit: \(audioServiceBit)")
        log("[BT] Rendering service bits: \(renderingBit)")
        log("[BT] Capturing service bits: \(capturingBit)")
        log("[BT] SDP services: \(serviceNames.isEmpty ? "none" : serviceNames.joined(separator: ", "))")
        log("[BT] DeviceCatalog match: \(catalogMatch?.name ?? "NONE")")
        log("[BT] Final classification: \(isAudio ? "AUDIO" : "NON-AUDIO")")
        log("[BT] Final support status: \(isSupported ? "SUPPORTED" : "UNSUPPORTED")")

        // Specific rejection logging
        if !isAudio {
            log("[BT] Ignoring non-audio device: \(resolvedName) (Classified as NON-AUDIO)")
            return
        }

        guard let profile = catalogMatch else {
            log("[BT] Unsupported audio device: \(resolvedName) (Not in DeviceCatalog)")
            return
        }

        // Supported device detected
        log("[BT] Supported device detected: \(resolvedName) / \(profile.name)")

        // Register for disconnect notification on this specific device
        let disconnectNotif = device.register(
            forDisconnectNotification: self,
            selector: #selector(deviceDisconnected(notification:device:))
        )
        if let notif = disconnectNotif {
            disconnectNotifications[normAddress] = notif
        }

        connectedDevices[normAddress] = (device: device, profile: profile, name: resolvedName)

        self.delegate?.audioDeviceConnected(name: resolvedName, profile: profile)
    }

    private func processDisconnectedDevice(address: String) {
        let normAddress = normalizeAddress(address)
        guard let tracked = connectedDevices.removeValue(forKey: normAddress) else {
            return
        }

        if let notif = disconnectNotifications.removeValue(forKey: normAddress) {
            notif.unregister()
        }
        pendingRetries.remove(normAddress)

        log("[BT] Supported device disconnected: \(tracked.name) [\(normAddress)]")

        self.delegate?.audioDeviceDisconnected(name: tracked.name, profile: tracked.profile)
    }
}
