import Foundation

public struct DeviceProfile: Sendable, Equatable {
    public let name: String
    public let modelCode: String
    public let serviceUUID: String
    public let hasCase: Bool
    public let isNeckband: Bool
    public let supportedFeatures: [FeatureId]

    public init(name: String, modelCode: String, serviceUUID: String, hasCase: Bool = true, isNeckband: Bool = false, supportedFeatures: [FeatureId] = [.inEar, .gameMode, .bassEngine, .spatialAudio, .dualConnect]) {
        self.name = name
        self.modelCode = modelCode
        self.serviceUUID = serviceUUID
        self.hasCase = hasCase
        self.isNeckband = isNeckband
        self.supportedFeatures = supportedFeatures
    }
}

public final class DeviceCatalog: @unchecked Sendable {
    public static let shared = DeviceCatalog()

    public let defaultProfile = DeviceProfile(
        name: "OnePlus Buds 3",
        modelCode: "063C14",
        serviceUUID: BudsUUIDs.serviceV1,
        hasCase: true,
        isNeckband: false
    )

    public let profiles: [DeviceProfile] = [
        // OnePlus Flagship
        DeviceProfile(name: "OnePlus Buds 3", modelCode: "063C14", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Pro 3", modelCode: "064014", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Pro 2", modelCode: "062014", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Pro 2R", modelCode: "063414", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Pro", modelCode: "060C14", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds 4", modelCode: "065414", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Z2", modelCode: "061014", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Buds Z", modelCode: "060814", serviceUUID: BudsUUIDs.serviceV1),

        // OnePlus Nord Series
        DeviceProfile(name: "OnePlus Nord Buds 2", modelCode: "062414", serviceUUID: BudsUUIDs.serviceV2, supportedFeatures: [.gameMode, .bassEngine]),
        DeviceProfile(name: "OnePlus Nord Buds 2r", modelCode: "062C14", serviceUUID: BudsUUIDs.serviceV2, supportedFeatures: [.gameMode]),
        DeviceProfile(name: "OnePlus Nord Buds 3 Pro", modelCode: "064414", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Nord Buds 3", modelCode: "065014", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Nord Buds 4 Pro", modelCode: "066814", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OnePlus Nord Buds CE", modelCode: "061C14", serviceUUID: BudsUUIDs.serviceV2),

        // Neckbands
        DeviceProfile(name: "OnePlus BulletsWireless Z2 ANC", modelCode: "050C14", serviceUUID: BudsUUIDs.serviceV2, hasCase: false, isNeckband: true, supportedFeatures: [.bassEngine]),
        DeviceProfile(name: "OnePlus Bullets Wireless Z3", modelCode: "051014", serviceUUID: BudsUUIDs.serviceV2, hasCase: false, isNeckband: true, supportedFeatures: [.bassEngine, .spatialAudio]),

        // OPPO Enco
        DeviceProfile(name: "OPPO Enco X3", modelCode: "067410", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OPPO Enco X2", modelCode: "063C10", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OPPO Enco Air4 Pro", modelCode: "067C10", serviceUUID: BudsUUIDs.serviceV1),
        DeviceProfile(name: "OPPO Enco Air3 Pro", modelCode: "065C10", serviceUUID: BudsUUIDs.serviceV2),
        DeviceProfile(name: "OPPO Enco Free3", modelCode: "066010", serviceUUID: BudsUUIDs.serviceV2),
        DeviceProfile(name: "OPPO Enco Free2", modelCode: "062010", serviceUUID: BudsUUIDs.serviceV1)
    ]

    private init() {}

    public func matchDevice(name: String?) -> DeviceProfile? {
        guard let name = name?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else {
            return nil
        }
        let clean = name.lowercased()

        // 1. Exact or case-insensitive match
        for p in profiles {
            if p.name.lowercased() == clean {
                return p
            }
        }

        // 2. Direct substring match
        for p in profiles {
            let pLower = p.name.lowercased()
            if clean.contains(pLower) || pLower.contains(clean) {
                return p
            }
        }

        // 3. Keyword heuristics
        if clean.contains("nord") && clean.contains("2") && !clean.contains("2r") && !clean.contains("3") {
            return profiles.first { $0.name == "OnePlus Nord Buds 2" }
        }
        if clean.contains("nord") && clean.contains("2r") {
            return profiles.first { $0.name == "OnePlus Nord Buds 2r" }
        }
        if clean.contains("nord") && clean.contains("3") && clean.contains("pro") {
            return profiles.first { $0.name == "OnePlus Nord Buds 3 Pro" }
        }
        if clean.contains("buds 3") && !clean.contains("nord") {
            return profiles.first { $0.name == "OnePlus Buds 3" }
        }
        if clean.contains("pro 3") {
            return profiles.first { $0.name == "OnePlus Buds Pro 3" }
        }
        if clean.contains("pro 2") {
            return profiles.first { $0.name == "OnePlus Buds Pro 2" }
        }
        if clean.contains("bullets") || clean.contains("z2") {
            return profiles.first { $0.name == "OnePlus BulletsWireless Z2 ANC" }
        }
        if clean.contains("oneplus") || clean.contains("oppo") || clean.contains("enco") {
            return defaultProfile
        }

        return nil
    }
}
