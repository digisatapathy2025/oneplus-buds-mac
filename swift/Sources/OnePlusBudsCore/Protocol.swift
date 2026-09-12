import Foundation

// ==============================================================================
// Service & Characteristic UUIDs (Multi-Generation Dual Service Architecture)
// ==============================================================================
public enum BudsUUIDs {
    public static let serviceV1 = "0000079A-D102-11E1-9B23-00025B00A5A5" // Newer buds (Buds 3, Buds Pro 3, etc.)
    public static let serviceV2 = "00001107-D102-11E1-9B23-00025B00A5A5" // Nord Buds 2, Bullets, Enco, etc.
    public static let txCharV1 = "0100079A-D102-11E1-9B23-00025B00A5A5"
    public static let rxCharV1 = "0200079A-D102-11E1-9B23-00025B00A5A5"
    public static let txCharLegacy = "db764ac8-4b08-7f25-aafe-59d03c27bae3"
    public static let rxCharLegacy = "db764ac8-4b08-7f25-aafe-59d03c27bae4"
    public static let fastPairService = "FE2C123A-8366-4814-8EB0-01DE32100BEA"
    public static let fastPairShort = "FE2C"
}

// ==============================================================================
// Hardware Feature Identifiers
// ==============================================================================
public enum FeatureId: UInt8, CaseIterable, Sendable {
    case inEar = 5
    case gameMode = 6
    case vocalEnhance = 9
    case dualConnect = 17     // 0x11
    case spatialAudio = 27    // 0x1B
    case bassEngine = 29      // 0x1D

    public var displayName: String {
        switch self {
        case .inEar: return "In-Ear Detection"
        case .gameMode: return "Game Mode (Low Latency)"
        case .vocalEnhance: return "Vocal Enhancement"
        case .dualConnect: return "Dual Connection"
        case .spatialAudio: return "Spatial Audio (3D Sound)"
        case .bassEngine: return "BassWave™ (Bass Boost)"
        }
    }
}

// ==============================================================================
// Noise Modes & Equalizers
// ==============================================================================
public enum PrimaryNoiseMode: String, CaseIterable, Sendable {
    case noiseCancellation = "Noise Cancellation"
    case off = "Off"
    case transparency = "Transparency"
}

public enum AncLevel: String, CaseIterable, Sendable {
    case auto = "Auto"
    case low = "Low"
    case moderate = "Moderate"
    case high = "High"

    public var hardwareMask: UInt8 {
        switch self {
        case .high: return 0x20
        case .moderate: return 0x20
        case .low: return 0x10
        case .auto: return 0x40
        }
    }
}

public enum EqualizerPreset: String, CaseIterable, Sendable {
    case balanced = "Balanced"
    case bass = "Bass"
    case clear = "Clear"
    case bold = "Bold"

    public var rawId: UInt8 {
        switch self {
        case .balanced: return 0x00
        case .bass: return 0x01
        case .clear: return 0x02
        case .bold: return 0x03
        }
    }

    public static func from(rawId: UInt8) -> EqualizerPreset {
        switch rawId {
        case 0x01: return .bass
        case 0x02: return .clear
        case 0x03: return .bold
        default: return .balanced
        }
    }
}

// ==============================================================================
// Battery State Structures
// ==============================================================================
public struct BatteryInfo: Sendable, Equatable {
    public var level: Int
    public var isCharging: Bool
    public var isConnected: Bool

    public init(level: Int = 0, isCharging: Bool = false, isConnected: Bool = false) {
        self.level = level
        self.isCharging = isCharging
        self.isConnected = isConnected
    }
}

public struct BudsBatteryState: Sendable, Equatable {
    public var left = BatteryInfo()
    public var right = BatteryInfo()
    public var caseBattery = BatteryInfo()
    public var single = BatteryInfo()

    public init() {}
}

// ==============================================================================
// Canonical BudsProtocol Engine
// ==============================================================================
public final class BudsProtocol: @unchecked Sendable {
    private var sequence: UInt8 = 1
    private let lock = NSLock()

    public init() {}

    public func nextSequence() -> UInt8 {
        lock.lock()
        defer { lock.unlock() }
        let current = sequence
        sequence = (sequence &+ 1) & 0x7F
        if sequence == 0 { sequence = 1 }
        return current
    }

    /// Wraps TLV bytes into an OPOv1 link-layer frame (0xAA header with varint length)
    public func wrapPacket(_ tlvBytes: [UInt8]) -> [UInt8] {
        let length = tlvBytes.count + 2
        var varint: [UInt8] = []
        var val = length
        while true {
            let b = UInt8(val & 0x7F)
            val >>= 7
            if val != 0 {
                varint.append(b | 0x80)
            } else {
                varint.append(b)
                break
            }
        }
        return [0xAA] + varint + [0x00, 0x00] + tlvBytes
    }

    public func buildHello() -> [UInt8] {
        return [0xAA, 0x07, 0x00, 0x00, 0x00, 0x01, nextSequence(), 0x00, 0x00, 0x12]
    }

    public func buildRegister() -> [UInt8] {
        return [0xAA, 0x0C, 0x00, 0x00, 0x00, 0x85, nextSequence(), 0x05, 0x00, 0x00, 0xB5, 0x50, 0xA0, 0x69]
    }

    public func buildBatteryQuery() -> [UInt8] {
        let tlv: [UInt8] = [0x06, 0x01, nextSequence(), 0x00, 0x00]
        return wrapPacket(tlv)
    }

    public func buildNoiseQuery() -> [UInt8] {
        let tlv: [UInt8] = [0x0C, 0x01, nextSequence(), 0x02, 0x00, 0x01, 0x01]
        return wrapPacket(tlv)
    }

    public func buildNoiseControl(modeMask: UInt8) -> [UInt8] {
        let tlv: [UInt8] = [0x04, 0x04, nextSequence(), 0x03, 0x00, 0x01, 0x01, modeMask]
        return wrapPacket(tlv)
    }

    public func buildFeatureQuery(featureIds: [UInt8]) -> [UInt8] {
        let count = UInt8(featureIds.count)
        let payload = [count] + featureIds
        let tlv: [UInt8] = [0x0D, 0x01, nextSequence(), UInt8(payload.count), 0x00] + payload
        return wrapPacket(tlv)
    }

    public func buildFeatureSet(featureId: UInt8, enable: Bool) -> [UInt8] {
        let val: UInt8 = enable ? 1 : 0
        let tlv: [UInt8] = [0x03, 0x04, nextSequence(), 0x02, 0x00, featureId, val]
        return wrapPacket(tlv)
    }

    public func buildEqSet(presetId: UInt8) -> [UInt8] {
        let tlv: [UInt8] = [0x06, 0x04, nextSequence(), 0x01, 0x00, presetId]
        return wrapPacket(tlv)
    }

    public static func parseTLVPacket(_ rawData: [UInt8]) -> (cmdId: UInt16, seq: UInt8, payload: [UInt8])? {
        guard rawData.count >= 4, rawData[0] == 0xAA else { return nil }
        var idx = 1
        while idx < rawData.count && (rawData[idx] & 0x80) != 0 {
            idx += 1
        }
        idx += 3 // Skip varint + 2 reserved bytes
        guard rawData.count >= idx + 5 else { return nil }

        let tlv = Array(rawData[idx...])
        let cmdId = UInt16(tlv[0]) | (UInt16(tlv[1]) << 8)
        let seq = tlv[2]
        let dataLen = Int(tlv[3]) | (Int(tlv[4]) << 8)
        guard tlv.count >= 5 + dataLen else { return nil }
        let payload = Array(tlv[5..<(5 + dataLen)])
        return (cmdId, seq, payload)
    }

    public static func parseBatteryPayload(_ payload: [UInt8], isNeckband: Bool = false) -> BudsBatteryState {
        var state = BudsBatteryState()
        guard payload.count >= 2 else { return state }
        let count = Int(payload[1])
        var pIdx = 2
        var seen = Set<String>()

        for _ in 0..<count {
            if pIdx + 1 < payload.count {
                let devType = payload[pIdx]
                let raw = payload[pIdx + 1]
                let lvl = Int(raw & 0x7F)
                let charging = (raw & 0x80) != 0
                let connected = lvl > 0

                switch devType {
                case 1:
                    seen.insert("left")
                    state.left = BatteryInfo(level: lvl, isCharging: charging, isConnected: connected)
                case 2:
                    seen.insert("right")
                    state.right = BatteryInfo(level: lvl, isCharging: charging, isConnected: connected)
                case 3:
                    seen.insert("case")
                    state.caseBattery = BatteryInfo(level: lvl, isCharging: charging, isConnected: connected)
                case 0, 4:
                    seen.insert("single")
                    state.single = BatteryInfo(level: lvl, isCharging: charging, isConnected: connected)
                default:
                    break
                }
                if isNeckband {
                    state.single = BatteryInfo(level: lvl, isCharging: charging, isConnected: connected)
                }
                pIdx += 2
            }
        }
        return state
    }

    public static func decodeNoiseMode(mask: UInt16, lastAncMode: AncLevel = .auto) -> (primary: PrimaryNoiseMode, level: AncLevel) {
        if (mask & 0x0100) != 0 || mask == 0x0004 || mask == 0x0002 {
            return (.transparency, lastAncMode)
        }
        if (mask & 0x0008) != 0 || mask == 0x0001 {
            return (.off, lastAncMode)
        }
        if (mask & 0x0040) != 0 || (mask & 0x0080) != 0 {
            return (.noiseCancellation, .auto)
        }
        if (mask & 0x0020) != 0 {
            let lvl: AncLevel = (lastAncMode == .moderate) ? .moderate : .high
            return (.noiseCancellation, lvl)
        }
        if (mask & 0x0010) != 0 {
            return (.noiseCancellation, .low)
        }
        return (.off, lastAncMode)
    }
}
