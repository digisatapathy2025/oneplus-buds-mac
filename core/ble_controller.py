#!/usr/bin/env python3
"""
Canonical BLE Controller & State Management for OnePlus / OPPO / Realme Earbuds.
Provides unified state caching, command building, notification parsing, and pluggable transports.
"""

import os
import sys
import json
import time
import subprocess
from typing import Optional, Dict, Any, List, Callable

from core.protocol import (
    BudsProtocol,
    BatteryState,
    decode_noise_mode,
    normalize_noise_mode,
    get_noise_mode_mask,
    NOISE_MODES,
    PRIMARY_NOISE_MODES,
    ANC_MODES,
    EQ_PRESETS,
    EQ_PRESETS_BY_ID,
    FEATURE_IN_EAR,
    FEATURE_GAME_MODE,
    FEATURE_VOCAL_ENHANCE,
    FEATURE_DUAL_CONNECT,
    FEATURE_SPATIAL_AUDIO,
    FEATURE_BASS_ENGINE,
    FEATURE_NAMES,
    CMD_BATTERY_RESP,
    CMD_FEATURE_RESP,
    CMD_MULTIPLEXED_EVENT,
    CMD_NOISE_RESP,
    CMD_NOISE_ACK,
    CMD_FEATURE_ACK,
    CMD_EQ_ACK_1,
    CMD_EQ_ACK_2,
    CMD_WEAR_EVENT_1,
    CMD_WEAR_EVENT_2,
)

from device_manager import DeviceProfile, DEFAULT_PROFILE, get_device_profile, match_supported_device

CONFIG_FILE = os.path.expanduser("~/.buds_controller_cache.json")


# ==============================================================================
# System Media Control (For In-Ear Detection Auto-Pause & Resume)
# ==============================================================================
def send_system_media_key(key_code: int = 16):
    """Posts a global HID media key event (16 = NX_KEYTYPE_PLAY/PAUSE)."""
    try:
        import AppKit
        event_down = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeSystemDefined, AppKit.NSZeroPoint, 0xa00, 0, 0, None, 8, (key_code << 16) | (0xa << 8), -1
        )
        event_up = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSEventTypeSystemDefined, AppKit.NSZeroPoint, 0xb00, 0, 0, None, 8, (key_code << 16) | (0xb << 8), -1
        )
        if event_down and event_up:
            AppKit.CGEventPost(AppKit.kCGHIDEventTap, event_down.CGEvent())
            AppKit.CGEventPost(AppKit.kCGHIDEventTap, event_up.CGEvent())
    except Exception:
        pass


def pause_system_media():
    """Pauses Spotify, Apple Music, or sends global Play/Pause key."""
    script = '''
    try
        if application "Spotify" is running then
            tell application "Spotify"
                if player state is playing then
                    pause
                    return "paused_spotify"
                end if
            end tell
        end if
    end try
    try
        if application "Music" is running then
            tell application "Music"
                if player state is playing then
                    pause
                    return "paused_music"
                end if
            end tell
        end if
    end try
    return "media_key"
    '''
    try:
        res = subprocess.check_output(["osascript", "-e", script]).decode().strip()
        if res == "media_key":
            send_system_media_key(16)
    except Exception:
        pass


def resume_system_media():
    """Resumes Spotify, Apple Music, or sends global Play/Pause key."""
    script = '''
    try
        if application "Spotify" is running then
            tell application "Spotify"
                if player state is not playing then
                    play
                    return "resumed_spotify"
                end if
            end tell
        end if
    end try
    try
        if application "Music" is running then
            tell application "Music"
                if player state is not playing then
                    play
                    return "resumed_music"
                end if
            end tell
        end if
    end try
    return "media_key"
    '''
    try:
        res = subprocess.check_output(["osascript", "-e", script]).decode().strip()
        if res == "media_key":
            send_system_media_key(16)
    except Exception:
        pass


# ==============================================================================
# Live State Container
# ==============================================================================
class BudsState:
    def __init__(self):
        self.address: Optional[str] = None
        self.device_name: str = "OnePlus Buds 3"
        self.profile: DeviceProfile = DEFAULT_PROFILE

        self.is_connected: bool = False
        self.is_connecting: bool = False
        self.status_message: str = "Disconnected"

        self.battery: Dict[str, Dict[str, Any]] = {
            "left": {"level": 0, "charging": False, "connected": False},
            "right": {"level": 0, "charging": False, "connected": False},
            "case": {"level": 0, "charging": False, "connected": False},
            "single": {"level": 0, "charging": False, "connected": False},
        }

        self.features: Dict[int, bool] = {
            FEATURE_IN_EAR: False,
            FEATURE_GAME_MODE: False,
            FEATURE_VOCAL_ENHANCE: False,
            FEATURE_DUAL_CONNECT: False,
            FEATURE_SPATIAL_AUDIO: False,
            FEATURE_BASS_ENGINE: False,
        }

        self.last_primary_mode: str = "Noise Cancellation"
        self.current_noise_mode: str = "Auto"
        self.last_anc_mode: str = "Auto"
        self.current_eq: str = "Balanced"

        self.show_battery_in_bar: bool = False
        self.auto_pause_on_wear: bool = True
        self.hide_when_disconnected: bool = False
        self.last_wear_state: bool = False

        self.timestamp: float = time.time()
        self.load_cache()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "name": self.device_name,
            "product_id": self.profile.product_id if self.profile else "063C14",
            "device_type": self.profile.device_type if self.profile else "T1",
            "battery": self.battery,
            "features": {str(k): v for k, v in self.features.items()},
            "last_primary_mode": self.last_primary_mode,
            "current_noise_mode": self.current_noise_mode,
            "last_anc_mode": self.last_anc_mode,
            "current_eq": self.current_eq,
            "show_battery_in_bar": self.show_battery_in_bar,
            "auto_pause_on_wear": self.auto_pause_on_wear,
            "hide_when_disconnected": self.hide_when_disconnected,
            "timestamp": time.time(),
        }

    def update_from_dict(self, data: Dict[str, Any]):
        if not data:
            return
        if "address" in data and data["address"]:
            self.address = data["address"]
        if "name" in data and data["name"]:
            self.device_name = data["name"]
        if "product_id" in data and data["product_id"]:
            prof = get_device_profile(data["product_id"])
            if prof:
                self.profile = prof
        if "battery" in data and isinstance(data["battery"], dict):
            for k, v in data["battery"].items():
                if k in self.battery and isinstance(v, dict):
                    self.battery[k].update(v)
        if "features" in data and isinstance(data["features"], dict):
            for k, v in data["features"].items():
                try:
                    self.features[int(k)] = bool(v)
                except ValueError:
                    pass
        for field in ["last_primary_mode", "current_noise_mode", "last_anc_mode", "current_eq"]:
            if field in data and data[field]:
                setattr(self, field, data[field])
        for bool_field in ["show_battery_in_bar", "auto_pause_on_wear", "hide_when_disconnected"]:
            if bool_field in data:
                setattr(self, bool_field, bool(data[bool_field]))
        self.timestamp = data.get("timestamp", time.time())

    def load_cache(self, path: str = CONFIG_FILE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.update_from_dict(data)
            except Exception as e:
                print(f"[BudsState] Error loading cache: {e}", file=sys.stderr)

    def save_cache(self, path: str = CONFIG_FILE):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as e:
            print(f"[BudsState] Error saving cache: {e}", file=sys.stderr)


# ==============================================================================
# Pluggable Transport Interface
# ==============================================================================
class BaseTransport:
    def send_bytes(self, data: bytearray) -> bool:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError


# ==============================================================================
# Canonical Shared BLE Controller
# ==============================================================================
class BaseBudsController:
    """
    Central controller that binds BudsProtocol, BudsState, and any pluggable transport.
    """
    def __init__(self, transport: Optional[BaseTransport] = None, on_update: Optional[Callable[[], None]] = None):
        self.protocol = BudsProtocol()
        self.state = BudsState()
        self.transport = transport
        self.on_update = on_update

    def set_transport(self, transport: BaseTransport):
        self.transport = transport

    def notify_ui(self):
        if self.on_update:
            try:
                self.on_update()
            except Exception as e:
                print(f"[BaseBudsController] Error in on_update callback: {e}", file=sys.stderr)

    def send_bytes(self, pkt: bytearray) -> bool:
        if self.transport:
            return self.transport.send_bytes(pkt)
        return False

    # --------------------------------------------------------------------------
    # Notification & Response Parser
    # --------------------------------------------------------------------------
    def parse_notification(self, raw_data: bytearray) -> Optional[int]:
        """
        Unpacks incoming BLE notifications according to the OPOv1 TLV specification.
        Returns the command ID processed, or None.
        """
        unpacked = self.protocol.parse_tlv_packet(raw_data)
        if not unpacked:
            return None

        cmd_id, seq, payload = unpacked

        # 0x8106: Battery Response
        if cmd_id == CMD_BATTERY_RESP:
            bat = self.protocol.parse_battery_payload(payload, is_neckband=self.state.profile.is_neckband)
            for k, v in bat.items():
                self.state.battery[k] = {"level": v.level, "charging": v.charging, "connected": v.connected}
            self.state.save_cache()
            self.notify_ui()
            return cmd_id

        # 0x810D: Feature Query Response
        elif cmd_id == CMD_FEATURE_RESP:
            if len(payload) >= 2:
                count = payload[1]
                p_idx = 2
                for _ in range(count):
                    if p_idx + 1 < len(payload):
                        fid = payload[p_idx]
                        val = payload[p_idx + 1] != 0
                        self.state.features[fid] = val
                        p_idx += 2
                self.state.save_cache()
                self.notify_ui()
            return cmd_id

        # 0x0204: Multiplexed State Push Notification
        elif cmd_id == CMD_MULTIPLEXED_EVENT:
            if len(payload) >= 2:
                subsystem = payload[0]
                # Subsystem 0x01: Live Battery Push Report
                if subsystem == 0x01 and len(payload) >= 4:
                    bat = self.protocol.parse_battery_payload(payload, is_neckband=self.state.profile.is_neckband)
                    for k, v in bat.items():
                        self.state.battery[k] = {"level": v.level, "charging": v.charging, "connected": v.connected}
                    self.state.save_cache()
                    self.notify_ui()
                # Subsystem 0x03: Noise Control State Event (Hardware Pinch or Switch)
                elif subsystem == 0x03 and len(payload) >= 4:
                    mask = payload[3]
                    if len(payload) >= 5:
                        mask |= (payload[4] << 8)
                    mode_name = decode_noise_mode(mask, self.state.last_anc_mode)
                    if mode_name:
                        self.state.current_noise_mode = mode_name
                        if mode_name in ANC_MODES:
                            self.state.last_anc_mode = mode_name
                            self.state.last_primary_mode = "Noise Cancellation"
                        elif mode_name in ["Off", "Transparency"]:
                            self.state.last_primary_mode = mode_name
                        self.state.save_cache()
                        self.notify_ui()
            return cmd_id

        # 0x810C: Noise Control Query Response
        elif cmd_id == CMD_NOISE_RESP:
            if len(payload) >= 4:
                mask = payload[3]
                if len(payload) >= 5:
                    mask |= (payload[4] << 8)
                mode_name = decode_noise_mode(mask, self.state.last_anc_mode)
                if mode_name:
                    self.state.current_noise_mode = mode_name
                    if mode_name in ANC_MODES:
                        self.state.last_anc_mode = mode_name
                        self.state.last_primary_mode = "Noise Cancellation"
                    elif mode_name in ["Off", "Transparency"]:
                        self.state.last_primary_mode = mode_name
                    self.state.save_cache()
                    self.notify_ui()
            return cmd_id

        # 0x8404: Set Noise Mode Execution ACK
        elif cmd_id == CMD_NOISE_ACK:
            return cmd_id

        # 0x8403: Feature Toggle Execution ACK
        elif cmd_id == CMD_FEATURE_ACK:
            return cmd_id

        # 0x8406 / 0x0504: EQ Preset ACK / Update
        elif cmd_id == CMD_EQ_ACK_1 or cmd_id == CMD_EQ_ACK_2:
            if len(payload) >= 2:
                pid = payload[1]
                eq_name = EQ_PRESETS_BY_ID.get(pid)
                if eq_name:
                    self.state.current_eq = eq_name
                    self.state.save_cache()
                    self.notify_ui()
            return cmd_id

        # 0x011C / 0x811C: In-Ear Wear Detection Event
        elif cmd_id == CMD_WEAR_EVENT_1 or cmd_id == CMD_WEAR_EVENT_2:
            if len(payload) >= 2:
                wear_byte = payload[1]
                is_worn = (wear_byte >= 2)
                if self.state.auto_pause_on_wear and self.state.features.get(FEATURE_IN_EAR, True):
                    if self.state.last_wear_state and not is_worn:
                        pause_system_media()
                    elif not self.state.last_wear_state and is_worn:
                        resume_system_media()
                self.state.last_wear_state = is_worn
            return cmd_id

        return cmd_id

    # --------------------------------------------------------------------------
    # Outbound Commands
    # --------------------------------------------------------------------------
    def set_primary_mode(self, mode_name: str) -> bool:
        mode_name = normalize_noise_mode(mode_name) or mode_name
        self.state.last_primary_mode = mode_name
        if mode_name == "Noise Cancellation":
            target_anc = self.state.last_anc_mode if self.state.last_anc_mode in ANC_MODES else "Auto"
            mask = NOISE_MODES.get(target_anc, 0x40)
            self.state.current_noise_mode = target_anc
        elif mode_name == "Transparency":
            mask = NOISE_MODES.get("Transparency", 0x04)
            self.state.current_noise_mode = "Transparency"
        else:
            mask = NOISE_MODES.get("Off", 0x01)
            self.state.current_noise_mode = "Off"

        self.state.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_noise_control(mask))

    def set_noise_mode(self, anc_mode: str) -> bool:
        anc_mode = normalize_noise_mode(anc_mode) or anc_mode
        if anc_mode in ANC_MODES:
            self.state.last_anc_mode = anc_mode
            self.state.last_primary_mode = "Noise Cancellation"
            self.state.current_noise_mode = anc_mode
            mask = NOISE_MODES.get(anc_mode, 0x40)
        elif anc_mode in ["Off", "Transparency"]:
            self.state.last_primary_mode = anc_mode
            self.state.current_noise_mode = anc_mode
            mask = NOISE_MODES.get(anc_mode, 0x01)
        else:
            return False

        self.state.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_noise_control(mask))

    def set_feature(self, feature_id: int, enable: bool) -> bool:
        self.state.features[feature_id] = enable
        self.state.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_feature_set(feature_id, enable))

    def set_eq(self, preset_name: str) -> bool:
        title_case = preset_name.strip().capitalize()
        pid = EQ_PRESETS.get(title_case)
        if pid is not None:
            self.state.current_eq = title_case
            self.state.save_cache()
            self.notify_ui()
            return self.send_bytes(self.protocol.build_eq_set(pid))
        return False

    def query_battery(self) -> bool:
        return self.send_bytes(self.protocol.build_battery_query())

    def query_noise(self) -> bool:
        return self.send_bytes(self.protocol.build_noise_query())

    def query_features(self, feature_ids: Optional[List[int]] = None) -> bool:
        if not feature_ids:
            feature_ids = [
                FEATURE_IN_EAR,
                FEATURE_GAME_MODE,
                FEATURE_VOCAL_ENHANCE,
                FEATURE_DUAL_CONNECT,
                FEATURE_SPATIAL_AUDIO,
                FEATURE_BASS_ENGINE
            ]
        return self.send_bytes(self.protocol.build_feature_query(feature_ids))

    def refresh(self):
        self.query_battery()
        self.query_noise()
        self.query_features()
