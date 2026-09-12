#!/usr/bin/env python3
"""
Canonical Protocol Engine & Frame Parser for OnePlus / OPPO / Realme Earbuds.
Reverse-engineered from com.heytap.headset (HeyMelody v116.9.0) with OPOv1 framing.
"""

from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

# ==============================================================================
# Service & Characteristic UUIDs (Multi-Generation Dual Service Architecture)
# ==============================================================================
SERVICE_UUID_V1 = "0000079A-D102-11E1-9B23-00025B00A5A5"
SERVICE_UUID_V2 = "00001107-D102-11E1-9B23-00025B00A5A5"

TX_CHAR_V1 = "0100079A-D102-11E1-9B23-00025B00A5A5"
RX_CHAR_V1 = "0200079A-D102-11E1-9B23-00025B00A5A5"

TX_CHAR_LEGACY = "db764ac8-4b08-7f25-aafe-59d03c27bae3"
RX_CHAR_LEGACY = "db764ac8-4b08-7f25-aafe-59d03c27bae4"

# Fast Pair Auxiliary Telemetry Service
FE2C_SERVICE_UUID = "FE2C123A-8366-4814-8EB0-01DE32100BEA"
FE2C_SHORT_UUID = "FE2C"

# ==============================================================================
# Feature IDs
# ==============================================================================
FEATURE_IN_EAR = 5
FEATURE_GAME_MODE = 6
FEATURE_VOCAL_ENHANCE = 9
FEATURE_DUAL_CONNECT = 17     # 0x11
FEATURE_SPATIAL_AUDIO = 27    # 0x1B
FEATURE_BASS_ENGINE = 29      # 0x1D

FEATURE_NAMES: Dict[int, str] = {
    FEATURE_IN_EAR: "In-Ear Detection",
    FEATURE_GAME_MODE: "Game Mode (Low Latency)",
    FEATURE_VOCAL_ENHANCE: "Vocal Enhancement",
    FEATURE_DUAL_CONNECT: "Dual Connection",
    FEATURE_SPATIAL_AUDIO: "Spatial Audio (3D Sound)",
    FEATURE_BASS_ENGINE: "BassWave™ (Bass Boost)",
}

# ==============================================================================
# Noise Control Modes & Bitmasks
# ==============================================================================
PRIMARY_NOISE_MODES = ["Noise Cancellation", "Off", "Transparency"]
ANC_MODES = ["High", "Moderate", "Low", "Auto"]

ANC_DESCRIPTIONS = {
    "High": "High — Maximum noise cancellation",
    "Moderate": "Moderate — Balanced noise cancellation",
    "Low": "Low — Minimal noise cancellation",
    "Auto": "Auto — Dynamically adjusts based on ambient noise levels",
}

# Hardware command masks
NOISE_MODES: Dict[str, int] = {
    "High": 0x20,      # maximum noise cancellation (Depth)
    "Moderate": 0x20,  # balanced noise cancellation
    "Low": 0x10,       # minimal noise cancellation (Mild)
    "Auto": 0x40,      # dynamically adjusts based on ambient noise (Smart)
    "Transparency": 0x04,
    "Off": 0x01,
}

# Aliases for CLI and backwards compatibility
NOISE_MODE_ALIASES: Dict[str, str] = {
    "high": "High",
    "moderate": "Moderate",
    "low": "Low",
    "auto": "Auto",
    "smart": "Auto",
    "anc": "Auto",
    "depth": "High",
    "mild": "Low",
    "transparency": "Transparency",
    "transparent": "Transparency",
    "off": "Off",
    "noise cancellation": "Auto",
}

def normalize_noise_mode(name: str) -> Optional[str]:
    """Maps any case/alias to canonical title-cased mode string."""
    if not name:
        return None
    clean = name.strip().lower()
    return NOISE_MODE_ALIASES.get(clean)

def get_noise_mode_mask(mode_name: str) -> int:
    """Returns the hardware command mask for a given noise mode name or alias."""
    canon = normalize_noise_mode(mode_name) or mode_name
    return NOISE_MODES.get(canon, 0x01)

def decode_noise_mode(mask: int, last_anc_mode: str = "Auto") -> Optional[str]:
    """
    Decodes hardware notification and query bitmasks to the canonical noise mode string.
    Implements the Sept 11 fix with correct 0x04 Transparency mask.
    """
    # 1. Transparency (protocolIndex 8 = 0x0100, or parent protocolIndex 2 = 0x0004 / 0x0002)
    if (mask & 0x0100) or (mask == 0x0004) or (mask == 0x0002):
        return "Transparency"
    # 2. Off (protocolIndex 3 = 0x0008, or parent protocolIndex 0 = 0x0001)
    if (mask & 0x0008) or (mask == 0x0001):
        return "Off"
    # 3. Auto ANC (protocolIndex 6 = 0x0040, or personalized protocolIndex 7 = 0x0080)
    if (mask & 0x0040) or (mask & 0x0080):
        return "Auto"
    # 4. Depth / Moderate ANC (protocolIndex 5 = 0x0020)
    if mask & 0x0020:
        return "Moderate" if last_anc_mode == "Moderate" else "High"
    # 5. Mild / Low ANC (protocolIndex 4 = 0x0010)
    if mask & 0x0010:
        return "Low"
    return None

# ==============================================================================
# Equalizer Presets
# ==============================================================================
EQ_PRESETS: Dict[str, int] = {
    "Balanced": 0x00,
    "Bass": 0x01,
    "Clear": 0x02,
    "Bold": 0x03,
}
EQ_PRESETS_BY_ID: Dict[int, str] = {v: k for k, v in EQ_PRESETS.items()}

# ==============================================================================
# Command IDs
# ==============================================================================
CMD_BATTERY_RESP = 0x8106
CMD_FEATURE_RESP = 0x810D
CMD_MULTIPLEXED_EVENT = 0x0204
CMD_NOISE_RESP = 0x810C
CMD_NOISE_ACK = 0x8404
CMD_FEATURE_ACK = 0x8403
CMD_EQ_ACK_1 = 0x8406
CMD_EQ_ACK_2 = 0x0504
CMD_WEAR_EVENT_1 = 0x011C
CMD_WEAR_EVENT_2 = 0x811C


@dataclass
class BatteryState:
    level: int = 0
    charging: bool = False
    connected: bool = False


# ==============================================================================
# Canonical BudsProtocol Engine
# ==============================================================================
class BudsProtocol:
    def __init__(self):
        self.seq = 1

    def next_seq(self) -> int:
        s = self.seq
        self.seq = (self.seq + 1) & 0x7F
        if self.seq == 0:
            self.seq = 1
        return s

    @staticmethod
    def wrap_packet(tlv_bytes: bytearray) -> bytearray:
        """Wraps a TLV packet inside an OPOv1 link-layer frame (0xAA header)."""
        length = len(tlv_bytes) + 2
        varint = bytearray()
        val = length
        while True:
            b = val & 0x7F
            val >>= 7
            if val != 0:
                varint.append(b | 0x80)
            else:
                varint.append(b)
                break
        return bytearray([0xAA]) + varint + bytearray([0x00, 0x00]) + tlv_bytes

    def build_hello(self) -> bytearray:
        return bytearray([0xAA, 0x07, 0x00, 0x00, 0x00, 0x01, self.next_seq(), 0x00, 0x00, 0x12])

    def build_register(self) -> bytearray:
        return bytearray([0xAA, 0x0C, 0x00, 0x00, 0x00, 0x85, self.next_seq(), 0x05, 0x00, 0x00, 0xB5, 0x50, 0xA0, 0x69])

    def build_battery_query(self) -> bytearray:
        tlv = bytearray([0x06, 0x01, self.next_seq(), 0x00, 0x00])
        return self.wrap_packet(tlv)

    def build_noise_query(self) -> bytearray:
        tlv = bytearray([0x0C, 0x01, self.next_seq(), 0x02, 0x00, 0x01, 0x01])
        return self.wrap_packet(tlv)

    def build_noise_control(self, mode_mask: int) -> bytearray:
        tlv = bytearray([0x04, 0x04, self.next_seq(), 0x03, 0x00, 0x01, 0x01, mode_mask])
        return self.wrap_packet(tlv)

    def build_feature_query(self, feature_ids: List[int]) -> bytearray:
        count = len(feature_ids)
        payload = bytearray([count]) + bytearray(feature_ids)
        tlv = bytearray([0x0D, 0x01, self.next_seq(), len(payload), 0x00]) + payload
        return self.wrap_packet(tlv)

    def build_feature_set(self, feature_id: int, enable: bool) -> bytearray:
        val = 1 if enable else 0
        tlv = bytearray([0x03, 0x04, self.next_seq(), 0x02, 0x00, feature_id, val])
        return self.wrap_packet(tlv)

    def build_eq_set(self, preset_id: int) -> bytearray:
        tlv = bytearray([0x06, 0x04, self.next_seq(), 0x01, 0x00, preset_id])
        return self.wrap_packet(tlv)

    @staticmethod
    def parse_tlv_packet(raw_data: bytearray) -> Optional[Tuple[int, int, bytearray]]:
        """
        Unpacks OPOv1 link-layer frame (0xAA header).
        Returns (cmd_id, seq, payload) or None if invalid.
        """
        if len(raw_data) < 4 or raw_data[0] != 0xAA:
            return None
        idx = 1
        while idx < len(raw_data) and (raw_data[idx] & 0x80) != 0:
            idx += 1
        idx += 3  # skip varint + 2 control/reserved bytes
        tlv = raw_data[idx:]
        if len(tlv) < 5:
            return None

        cmd_id = int.from_bytes(tlv[0:2], byteorder="little")
        seq = tlv[2]
        data_len = int.from_bytes(tlv[3:5], byteorder="little")
        payload = tlv[5:5 + data_len]
        return cmd_id, seq, payload

    @staticmethod
    def parse_battery_payload(payload: bytearray, is_neckband: bool = False) -> Dict[str, BatteryState]:
        """
        Decodes hardware battery payload.
        Handles Type N Neckbands unified gauge as well as TWS left/right/case.
        """
        result: Dict[str, BatteryState] = {
            "left": BatteryState(),
            "right": BatteryState(),
            "case": BatteryState(),
            "single": BatteryState(),
        }
        if len(payload) < 2:
            return result

        count = payload[1]
        p_idx = 2
        dev_map = {0: "single", 1: "left", 2: "right", 3: "case", 4: "single"}
        seen = set()

        for _ in range(count):
            if p_idx + 1 < len(payload):
                dev_type = payload[p_idx]
                raw = payload[p_idx + 1]
                lvl = raw & 0x7F
                charging = (raw & 0x80) != 0
                name = dev_map.get(dev_type)
                if name:
                    seen.add(name)
                    result[name] = BatteryState(level=lvl, charging=charging, connected=(lvl > 0))
                    if is_neckband and name in ["left", "single", "case"]:
                        result["single"] = BatteryState(level=lvl, charging=charging, connected=(lvl > 0))
                p_idx += 2

        for k in ["left", "right", "case", "single"]:
            if k not in seen and not (is_neckband and k == "single" and "single" in result and result["single"].connected):
                result[k] = BatteryState(level=0, charging=False, connected=False)

        return result
