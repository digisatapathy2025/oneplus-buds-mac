import Foundation
import IOBluetooth

@MainActor
public protocol SystemAudioMonitorDelegate: AnyObject {
    func audioDeviceConnected(name: String, profile: DeviceProfile)
    func audioDeviceDisconnected(name: String, profile: DeviceProfile)
}

public final class SystemAudioMonitor: @unchecked Sendable {
    public weak var delegate: SystemAudioMonitorDelegate?
    private var isRunning = false
    private var timer: Timer?
    private var lastConnectedName: String?
    private let lock = NSLock()

    public init() {}

    public static func findConnectedSupportedDevice() -> (profile: DeviceProfile, device: IOBluetoothDevice)? {
        guard let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] else {
            return nil
        }
        for dev in paired {
            if dev.isConnected() {
                let name = dev.nameOrAddress ?? ""
                if let profile = DeviceCatalog.shared.matchDevice(name: name) {
                    return (profile, dev)
                }
            }
        }
        return nil
    }

    public func start() {
        lock.lock()
        defer { lock.unlock() }
        guard !isRunning else { return }
        isRunning = true

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.checkConnectedDevices()
            self.timer = Timer.scheduledTimer(withTimeInterval: 2.5, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    self?.checkConnectedDevices()
                }
            }
        }
    }

    public func stop() {
        lock.lock()
        defer { lock.unlock() }
        isRunning = false
        timer?.invalidate()
        timer = nil
    }

    @MainActor
    private func checkConnectedDevices() {
        if let (profile, dev) = Self.findConnectedSupportedDevice() {
            let name = dev.nameOrAddress ?? profile.name
            if lastConnectedName != name {
                lastConnectedName = name
                delegate?.audioDeviceConnected(name: name, profile: profile)
            }
        } else {
            if let last = lastConnectedName {
                let profile = DeviceCatalog.shared.matchDevice(name: last) ?? DeviceCatalog.shared.defaultProfile
                lastConnectedName = nil
                delegate?.audioDeviceDisconnected(name: last, profile: profile)
            }
        }
    }
}
