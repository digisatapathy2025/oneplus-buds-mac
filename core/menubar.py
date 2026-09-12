#!/usr/bin/env python3
"""
AirPods-Style Native Menu Bar Agent for OnePlus / OPPO / Realme Earbuds.
Integrates inline IOBluetooth audio device monitoring, CoreBluetooth BLE communication,
live popover cards, dynamic 0px collapse, and local Unix Domain Socket IPC server.
"""

import sys
import os
import json
import time
import subprocess
from typing import Optional, Dict, Any, List

# Ensure parent and workspace are in path
_this_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_parent_dir = os.path.dirname(_this_dir)
for d in [_this_dir, _parent_dir]:
    if d and os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

import objc
import AppKit
import Foundation
import CoreBluetooth

from core.protocol import (
    BudsProtocol,
    decode_noise_mode,
    normalize_noise_mode,
    get_noise_mode_mask,
    NOISE_MODES,
    PRIMARY_NOISE_MODES,
    ANC_MODES,
    ANC_DESCRIPTIONS,
    EQ_PRESETS,
    FEATURE_IN_EAR,
    FEATURE_GAME_MODE,
    FEATURE_VOCAL_ENHANCE,
    FEATURE_DUAL_CONNECT,
    FEATURE_SPATIAL_AUDIO,
    FEATURE_BASS_ENGINE,
    FEATURE_NAMES,
    SERVICE_UUID_V1,
    SERVICE_UUID_V2,
    TX_CHAR_V1,
    RX_CHAR_V1,
    TX_CHAR_LEGACY,
    RX_CHAR_LEGACY,
    FE2C_SERVICE_UUID,
    FE2C_SHORT_UUID,
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

from core.ble_controller import (
    BudsState,
    pause_system_media,
    resume_system_media,
    CONFIG_FILE,
)

from core.ipc import BudsIPCServer

from device_manager import (
    get_device_profile,
    match_supported_device,
    is_supported_device,
    DeviceProfile,
    DEFAULT_PROFILE,
)

from bluetooth_monitor import (
    BluetoothAudioMonitor,
    is_bluetooth_audio_device,
    IOBluetoothDevice,
)

SERVICE_UUID = CoreBluetooth.CBUUID.UUIDWithString_(SERVICE_UUID_V1)
SERVICE_UUID_V2 = CoreBluetooth.CBUUID.UUIDWithString_(SERVICE_UUID_V2)
TX_CHAR_UUID = CoreBluetooth.CBUUID.UUIDWithString_(TX_CHAR_V1)
RX_CHAR_UUID = CoreBluetooth.CBUUID.UUIDWithString_(RX_CHAR_V1)
TX_CHAR_LEGACY_UUID = CoreBluetooth.CBUUID.UUIDWithString_(TX_CHAR_LEGACY)
RX_CHAR_LEGACY_UUID = CoreBluetooth.CBUUID.UUIDWithString_(RX_CHAR_LEGACY)
FE2C_SERVICE_UUID_CB = CoreBluetooth.CBUUID.UUIDWithString_(FE2C_SERVICE_UUID)
FE2C_SHORT_UUID_CB = CoreBluetooth.CBUUID.UUIDWithString_(FE2C_SHORT_UUID)

APP_PATH = "/Applications/OnePlus Buds.app"
ALT_APP_PATH = os.path.expanduser("~/Applications/OnePlus Buds.app")
GUI_SCRIPT_PATH = os.path.join(_parent_dir, "buds.py")


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [BudsApp] {msg}", flush=True)


def find_connected_supported_device():
    """Identifies if any supported Bluetooth audio device is currently connected to macOS."""
    if not IOBluetoothDevice:
        return None, None
    try:
        paired = IOBluetoothDevice.pairedDevices() or []
        for dev in paired:
            if dev.isConnected() and is_bluetooth_audio_device(dev):
                name = dev.getName() or dev.nameOrAddress() or ""
                profile = match_supported_device(name)
                if profile:
                    return profile, dev
    except Exception as e:
        log(f"Error checking connected devices: {e}")
    return None, None


def get_sf_symbol(name: str, size: float = 14.0, weight=AppKit.NSFontWeightMedium) -> Optional[AppKit.NSImage]:
    img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if img:
        cfg = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, weight)
        if cfg:
            img = img.imageWithSymbolConfiguration_(cfg)
    return img


# ==============================================================================
# Native CoreBluetooth Controller
# ==============================================================================
class NativeBudsBLEController(CoreBluetooth.NSObject):
    def init(self):
        self = objc.super(NativeBudsBLEController, self).init()
        if not self:
            return None

        self.protocol = BudsProtocol()
        self.state = BudsState()
        self.delegate = None  # Pointer to BudsAirPodsApp

        self.central = None
        self.peripheral = None
        self.tx_char = None
        self.rx_char = None
        self._handshake_started = False
        self.is_scanning = False
        self.connection_timeout_timer = None
        self.scan_timeout_timer = None

        # Load persisted state from ~/.buds_controller_cache.json
        self.state.load_cache()

        # Initialize native CBCentralManager on main dispatch queue
        self.central = CoreBluetooth.CBCentralManager.alloc().initWithDelegate_queue_(self, None)
        return self

    def cancel_connection_timeout(self):
        if self.connection_timeout_timer:
            self.connection_timeout_timer.invalidate()
            self.connection_timeout_timer = None

    def start_connection_timeout(self):
        self.cancel_connection_timeout()
        self.connection_timeout_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, "onConnectionTimeoutTimer:", None, False
        )

    def onConnectionTimeoutTimer_(self, _):
        self.connection_timeout_timer = None
        if self.state.is_connecting:
            log("CoreBluetooth connectPeripheral timed out after 5.0s. Cancelling connection.")
            if self.peripheral and self.central:
                try:
                    self.central.cancelPeripheralConnection_(self.peripheral)
                except Exception:
                    pass
            self.peripheral = None
            self.state.is_connecting = False
            self.state.status_message = "Connection Timed Out"
            self.notify_ui()
            # If a device profile is set, start targeted BLE scan to find its active advertising peripheral
            if self.state.profile and not self.is_scanning:
                self.start_targeted_scan()

    # Convenience accessors mapping to state
    @property
    def battery(self): return self.state.battery
    @property
    def features(self): return self.state.features
    @property
    def is_connected(self): return self.state.is_connected
    @is_connected.setter
    def is_connected(self, val): self.state.is_connected = val
    @property
    def is_connecting(self): return self.state.is_connecting
    @is_connecting.setter
    def is_connecting(self, val): self.state.is_connecting = val
    @property
    def profile(self): return self.state.profile
    @profile.setter
    def profile(self, val): self.state.profile = val
    @property
    def device_name(self): return self.state.device_name
    @device_name.setter
    def device_name(self, val): self.state.device_name = val
    @property
    def address(self): return self.state.address
    @address.setter
    def address(self, val): self.state.address = val
    @property
    def status_message(self): return self.state.status_message
    @status_message.setter
    def status_message(self, val): self.state.status_message = val
    @property
    def last_primary_mode(self): return self.state.last_primary_mode
    @last_primary_mode.setter
    def last_primary_mode(self, val): self.state.last_primary_mode = val
    @property
    def last_anc_mode(self): return self.state.last_anc_mode
    @last_anc_mode.setter
    def last_anc_mode(self, val): self.state.last_anc_mode = val
    @property
    def current_noise_mode(self): return self.state.current_noise_mode
    @current_noise_mode.setter
    def current_noise_mode(self, val): self.state.current_noise_mode = val
    @property
    def current_eq(self): return self.state.current_eq
    @current_eq.setter
    def current_eq(self, val): self.state.current_eq = val
    @property
    def show_battery_in_bar(self): return self.state.show_battery_in_bar
    @show_battery_in_bar.setter
    def show_battery_in_bar(self, val): self.state.show_battery_in_bar = val
    @property
    def auto_pause_on_wear(self): return self.state.auto_pause_on_wear
    @auto_pause_on_wear.setter
    def auto_pause_on_wear(self, val): self.state.auto_pause_on_wear = val
    @property
    def hide_when_disconnected(self): return self.state.hide_when_disconnected
    @hide_when_disconnected.setter
    def hide_when_disconnected(self, val): self.state.hide_when_disconnected = val

    def save_cache(self):
        self.state.save_cache()

    def load_cache(self):
        self.state.load_cache()

    def notify_ui(self):
        if self.delegate and hasattr(self.delegate, "update_ui_state"):
            self.delegate.update_ui_state()

    # --------------------------------------------------------------------------
    # CBCentralManager Delegate Methods
    # --------------------------------------------------------------------------
    def centralManagerDidUpdateState_(self, central):
        if central.state() == CoreBluetooth.CBManagerStatePoweredOn:
            # Check if a supported audio device is currently connected to macOS
            prof, dev = find_connected_supported_device()
            if prof:
                log(f"CBCentralManager powered on with active audio device: {prof.name}")
                self.state.profile = prof
                self.state.device_name = prof.name
                self.attempt_fast_connect()
            else:
                log("CBCentralManager powered on. No supported audio device connected. Remaining idle.")

    def onScanTimeoutTimer_(self, _):
        self.is_scanning = False
        self.scan_timeout_timer = None
        if self.central and self.central.isScanning():
            self.central.stopScan()
            log("Targeted BLE scan timed out (8.0s). Returned to idle.")
        if self.state.is_connecting:
            self.state.is_connecting = False
            self.state.status_message = "Disconnected"
            self.notify_ui()

    def start_targeted_scan(self):
        if not self.central or self.central.state() != CoreBluetooth.CBManagerStatePoweredOn:
            return
        if self.is_scanning:
            return
        self.is_scanning = True
        log(f"Starting targeted BLE scan for active device: {self.state.profile.name if self.state.profile else 'supported earbuds'}")
        # Passing None performs an open scan without service UUID filtering, ensuring earbuds
        # that omit 128-bit service UUIDs in their 31-byte adv payload are discovered and matched by name
        self.central.scanForPeripheralsWithServices_options_(None, None)
        if self.scan_timeout_timer:
            self.scan_timeout_timer.invalidate()
        self.scan_timeout_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            8.0, self, "onScanTimeoutTimer:", None, False
        )

    def attempt_fast_connect(self):
        if self.state.is_connected or self.state.is_connecting or not self.central:
            return
        if self.central.state() != CoreBluetooth.CBManagerStatePoweredOn:
            return

        self._handshake_started = False

        # Strictly synchronize with active Bluetooth audio device connected to macOS
        active_prof, _ = find_connected_supported_device()
        if active_prof:
            if not self.state.profile or self.state.profile.name != active_prof.name:
                log(f"Active audio device changed to '{active_prof.name}'. Invalidating cached address.")
                self.state.address = ""
                self._handshake_started = False
            self.state.profile = active_prof
            self.state.device_name = active_prof.name

        if not self.state.profile:
            log("No active supported Bluetooth audio device connected. Aborting fast connect.")
            return

        target_name = (self.state.profile.name or "").strip().lower()

        # 1. Zero-delay retrieve of already connected Bluetooth audio peripheral
        services_to_query = [
            SERVICE_UUID,
            SERVICE_UUID_V2,
            FE2C_SERVICE_UUID_CB,
            FE2C_SHORT_UUID_CB,
        ]
        if self.state.profile and self.state.profile.uuid:
            try:
                prof_uuid = CoreBluetooth.CBUUID.UUIDWithString_(self.state.profile.uuid)
                if prof_uuid not in services_to_query:
                    services_to_query.append(prof_uuid)
            except Exception:
                pass

        periphs = self.central.retrieveConnectedPeripheralsWithServices_(services_to_query)

        # Only check cached address if it strictly matches the current target device name (never hijack)
        if (not periphs or len(periphs) == 0) and self.state.address:
            try:
                nsuuid = Foundation.NSUUID.alloc().initWithUUIDString_(self.state.address)
                if nsuuid:
                    cached_periphs = self.central.retrievePeripheralsWithIdentifiers_([nsuuid])
                    if cached_periphs:
                        for cp in cached_periphs:
                            cp_name = (cp.name() or "").strip().lower()
                            if target_name and (target_name in cp_name or cp_name in target_name):
                                periphs = [cp]
                                break
            except Exception:
                pass

        target_periph = None
        if periphs and len(periphs) > 0:
            for p in periphs:
                p_name = (p.name() or "").strip()
                p_name_lower = p_name.lower()
                # Strict matching against active device profile
                matched = False
                if target_name and (target_name in p_name_lower or p_name_lower in target_name):
                    matched = True
                else:
                    cand = match_supported_device(p_name)
                    if cand and self.state.profile and cand.name.lower() == self.state.profile.name.lower():
                        matched = True
                if matched:
                    target_periph = p
                    break

        if target_periph:
            log(f"Fast retrieved matching peripheral: {target_periph.name()} [{target_periph.identifier().UUIDString()}]")
            self.state.is_connecting = True
            self.state.status_message = "Connecting..."
            self.peripheral = target_periph
            self.peripheral.setDelegate_(self)
            self.state.address = self.peripheral.identifier().UUIDString()
            self._handshake_started = False
            self.central.connectPeripheral_options_(self.peripheral, None)
            self.start_connection_timeout()
            self.notify_ui()
            return

        # 2. Targeted open BLE scan with strict device name matching
        self.start_targeted_scan()

    def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(self, central, peripheral, adv, rssi):
        name = peripheral.name()
        if not name and adv:
            name = adv.objectForKey_(CoreBluetooth.CBAdvertisementDataLocalNameKey)
        name = (name or "").strip()
        if not name:
            return

        target_name = (self.state.profile.name or "").strip().lower() if self.state.profile else ""
        name_lower = name.lower()

        matched_profile = None
        if target_name and (target_name in name_lower or name_lower in target_name):
            matched_profile = self.state.profile
        else:
            cand = match_supported_device(name)
            if cand and self.state.profile and cand.name.lower() == self.state.profile.name.lower():
                matched_profile = self.state.profile
            elif not self.state.profile and cand:
                matched_profile = cand

        if matched_profile:
            log(f"Discovered matching BLE peripheral: {name} [{peripheral.identifier().UUIDString()}]")
            self.is_scanning = False
            self.central.stopScan()
            if self.scan_timeout_timer:
                self.scan_timeout_timer.invalidate()
                self.scan_timeout_timer = None

            self.state.is_connecting = True
            self.state.status_message = "Connecting..."
            self.peripheral = peripheral
            self.peripheral.setDelegate_(self)
            self.state.address = self.peripheral.identifier().UUIDString()
            self.state.profile = matched_profile
            self.state.device_name = matched_profile.name
            self._handshake_started = False
            self.central.connectPeripheral_options_(self.peripheral, None)
            self.start_connection_timeout()
            self.notify_ui()

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        self.cancel_connection_timeout()
        self.state.is_connected = True
        self.state.is_connecting = False
        self.state.status_message = "Connected"
        self._handshake_started = False
        p_name = peripheral.name()
        if p_name and is_supported_device(p_name):
            self.state.profile = get_device_profile(p_name)
            self.state.device_name = self.state.profile.name
        self.save_cache()
        self.notify_ui()

        services_to_discover = [SERVICE_UUID, SERVICE_UUID_V2, FE2C_SERVICE_UUID_CB, FE2C_SHORT_UUID_CB]
        if self.state.profile and self.state.profile.uuid:
            try:
                prof_uuid = CoreBluetooth.CBUUID.UUIDWithString_(self.state.profile.uuid)
                if prof_uuid not in services_to_discover:
                    services_to_discover.append(prof_uuid)
            except Exception:
                pass
        peripheral.discoverServices_(services_to_discover)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
        self.cancel_connection_timeout()
        self.state.is_connected = False
        self.state.is_connecting = False
        self.peripheral = None
        self.tx_char = None
        self.rx_char = None
        self._handshake_started = False
        self.state.address = ""
        self.state.status_message = "Disconnected"
        if self.delegate and hasattr(self.delegate, "has_shown_connect_card"):
            self.delegate.has_shown_connect_card = False
        for k in ["left", "right", "case", "single"]:
            if k in self.state.battery:
                self.state.battery[k]["connected"] = False
        self.save_cache()
        self.notify_ui()

    def centralManager_didFailToConnectPeripheral_error_(self, central, peripheral, error):
        self.cancel_connection_timeout()
        self.state.is_connected = False
        self.state.is_connecting = False
        self.peripheral = None
        self._handshake_started = False
        self.state.address = ""
        self.state.status_message = "Connection Failed"
        if self.delegate and hasattr(self.delegate, "has_shown_connect_card"):
            self.delegate.has_shown_connect_card = False
        for k in ["left", "right", "case", "single"]:
            if k in self.state.battery:
                self.state.battery[k]["connected"] = False
        self.notify_ui()

    # --------------------------------------------------------------------------
    # CBPeripheral Delegate Methods
    # --------------------------------------------------------------------------
    def peripheral_didDiscoverServices_(self, peripheral, error):
        if not peripheral.services():
            return
        for s in peripheral.services():
            peripheral.discoverCharacteristics_forService_(None, s)

    def peripheral_didDiscoverCharacteristicsForService_error_(self, peripheral, service, error):
        if not service.characteristics():
            return
        for c in service.characteristics():
            u_str = c.UUID().UUIDString().upper()
            props = c.properties()
            if (u_str in [RX_CHAR_V1.upper(), RX_CHAR_LEGACY.upper()] or 
                ((service.UUID().isEqual_(SERVICE_UUID) or service.UUID().isEqual_(SERVICE_UUID_V2)) and (props & 16 != 0 or props & 32 != 0))):
                if not self.rx_char:
                    self.rx_char = c
                    peripheral.setNotifyValue_forCharacteristic_(True, c)
            if (u_str in [TX_CHAR_V1.upper(), TX_CHAR_LEGACY.upper()] or
                ((service.UUID().isEqual_(SERVICE_UUID) or service.UUID().isEqual_(SERVICE_UUID_V2)) and (props & 4 != 0 or props & 8 != 0))):
                if not self.tx_char:
                    self.tx_char = c
            elif service.UUID().isEqual_(FE2C_SERVICE_UUID_CB):
                if (props & 16 != 0) or (props & 32 != 0):
                    peripheral.setNotifyValue_forCharacteristic_(True, c)

        if self.tx_char and not self._handshake_started:
            self._handshake_started = True
            self.performSelector_withObject_afterDelay_("doHandshakeHello:", None, 0.15)

    def doHandshakeHello_(self, _):
        if self.peripheral and self.tx_char:
            self.send_bytes(self.protocol.build_hello())
            self.performSelector_withObject_afterDelay_("doHandshakeRegister:", None, 0.3)

    def doHandshakeRegister_(self, _):
        if self.peripheral and self.tx_char:
            self.send_bytes(self.protocol.build_register())
            self.performSelector_withObject_afterDelay_("doInitialQueries:", None, 0.35)

    def doInitialQueries_(self, _):
        if self.peripheral and self.tx_char:
            self.send_bytes(self.protocol.build_battery_query())
            self.send_bytes(self.protocol.build_noise_query())
            feature_ids = [FEATURE_IN_EAR, FEATURE_GAME_MODE, FEATURE_VOCAL_ENHANCE, FEATURE_DUAL_CONNECT, FEATURE_SPATIAL_AUDIO, FEATURE_BASS_ENGINE]
            self.send_bytes(self.protocol.build_feature_query(feature_ids))

    def send_bytes(self, pkt: bytearray) -> bool:
        if not self.peripheral or not self.tx_char:
            return False
        try:
            nsdata = AppKit.NSData.dataWithBytes_length_(bytes(pkt), len(pkt))
            self.peripheral.writeValue_forCharacteristic_type_(
                nsdata, self.tx_char, CoreBluetooth.CBCharacteristicWriteWithoutResponse
            )
            return True
        except Exception:
            return False

    def peripheral_didUpdateValueForCharacteristic_error_(self, peripheral, characteristic, error):
        if error:
            return
        data = characteristic.value()
        if not data:
            return
        raw_bytes = bytearray(data.bytes())
        self.parse_notification(raw_bytes)

    # --------------------------------------------------------------------------
    # Notification & Response Parser
    # --------------------------------------------------------------------------
    def parse_notification(self, raw_data: bytearray):
        unpacked = self.protocol.parse_tlv_packet(raw_data)
        if not unpacked:
            return
        cmd_id, seq, payload = unpacked

        # 0x8106: Battery Response
        if cmd_id == CMD_BATTERY_RESP:
            bat = self.protocol.parse_battery_payload(payload, is_neckband=self.state.profile.is_neckband)
            for k, v in bat.items():
                self.state.battery[k] = {"level": v.level, "charging": v.charging, "connected": v.connected}
            self.save_cache()
            self.notify_ui()
            if self.delegate and hasattr(self.delegate, "trigger_connect_card"):
                self.delegate.trigger_connect_card()

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
                self.save_cache()
                self.notify_ui()

        # 0x0204: Multiplexed State Push Notification
        elif cmd_id == CMD_MULTIPLEXED_EVENT:
            if len(payload) >= 2:
                subsystem = payload[0]
                if subsystem == 0x01 and len(payload) >= 4:
                    bat = self.protocol.parse_battery_payload(payload, is_neckband=self.state.profile.is_neckband)
                    for k, v in bat.items():
                        self.state.battery[k] = {"level": v.level, "charging": v.charging, "connected": v.connected}
                    self.save_cache()
                    self.notify_ui()
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
                        self.save_cache()
                        self.notify_ui()

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
                    self.save_cache()
                    self.notify_ui()

        # 0x8406 / 0x0504: EQ Preset ACK / Update
        elif cmd_id == CMD_EQ_ACK_1 or cmd_id == CMD_EQ_ACK_2:
            if len(payload) >= 2:
                pid = payload[1]
                for name, val in EQ_PRESETS.items():
                    if val == pid:
                        self.state.current_eq = name
                        break
                self.save_cache()
                self.notify_ui()

        # 0x011C / 0x811C: In-Ear Wear Detection Event
        elif cmd_id == CMD_WEAR_EVENT_1 or cmd_id == CMD_WEAR_EVENT_2:
            if len(payload) >= 2:
                wear_byte = payload[1]
                is_worn = (wear_byte >= 2)
                if self.state.auto_pause_on_wear and self.state.features.get(FEATURE_IN_EAR, True):
                    if getattr(self, "_last_wear_state", True) and not is_worn:
                        pause_system_media()
                    elif not getattr(self, "_last_wear_state", True) and is_worn:
                        resume_system_media()
                self._last_wear_state = is_worn

    # Outbound Commands
    def set_primary_mode(self, primary_mode: str) -> bool:
        primary_mode = normalize_noise_mode(primary_mode) or primary_mode
        self.state.last_primary_mode = primary_mode
        if primary_mode == "Noise Cancellation":
            target_anc = self.state.last_anc_mode if self.state.last_anc_mode in ANC_MODES else "Auto"
            mask = NOISE_MODES.get(target_anc, 0x40)
            self.state.current_noise_mode = target_anc
        elif primary_mode == "Transparency":
            mask = NOISE_MODES.get("Transparency", 0x04)
            self.state.current_noise_mode = "Transparency"
        else:
            mask = NOISE_MODES.get("Off", 0x01)
            self.state.current_noise_mode = "Off"

        self.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_noise_control(mask))

    def set_noise_mode(self, mode_name: str) -> bool:
        mode_name = normalize_noise_mode(mode_name) or mode_name
        if mode_name in ANC_MODES:
            self.state.last_anc_mode = mode_name
            self.state.last_primary_mode = "Noise Cancellation"
            self.state.current_noise_mode = mode_name
            mask = NOISE_MODES.get(mode_name, 0x40)
        elif mode_name in ["Off", "Transparency"]:
            self.state.last_primary_mode = mode_name
            self.state.current_noise_mode = mode_name
            mask = NOISE_MODES.get(mode_name, 0x01)
        else:
            return False

        self.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_noise_control(mask))

    def set_feature(self, feature_id: int, enable: bool) -> bool:
        self.state.features[feature_id] = enable
        self.save_cache()
        self.notify_ui()
        return self.send_bytes(self.protocol.build_feature_set(feature_id, enable))

    def set_eq(self, preset_name: str) -> bool:
        title_case = preset_name.strip().capitalize()
        pid = EQ_PRESETS.get(title_case)
        if pid is not None:
            self.state.current_eq = title_case
            self.save_cache()
            self.notify_ui()
            return self.send_bytes(self.protocol.build_eq_set(pid))
        return False

    def refresh(self):
        self.send_bytes(self.protocol.build_battery_query())
        self.send_bytes(self.protocol.build_noise_query())
        feature_ids = [FEATURE_IN_EAR, FEATURE_GAME_MODE, FEATURE_VOCAL_ENHANCE, FEATURE_DUAL_CONNECT, FEATURE_SPATIAL_AUDIO, FEATURE_BASS_ENGINE]
        self.send_bytes(self.protocol.build_feature_query(feature_ids))

    def disconnect(self):
        self.cancel_connection_timeout()
        self._handshake_started = False
        self.state.address = ""
        if self.peripheral and self.central:
            self.central.cancelPeripheralConnection_(self.peripheral)


# ==============================================================================
# Custom Native AppKit Views (AirPods & macOS System Settings Style)
# ==============================================================================
class FlippedVisualEffectView(AppKit.NSVisualEffectView):
    def isFlipped(self):
        return True


class RoundedCardView(AppKit.NSView):
    def initWithFrame_(self, frame):
        self = objc.super(RoundedCardView, self).initWithFrame_(frame)
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(12.0)
        self.layer().setMasksToBounds_(True)
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, dirtyRect):
        bounds = self.bounds()
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 12.0, 12.0)
        AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.045).setFill()
        path.fill()
        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(0.20).setStroke()
        path.setLineWidth_(1.0)
        path.stroke()


class SquircleBadgeView(AppKit.NSView):
    """macOS System Settings style rounded squircle badge container."""
    def initWithFrame_bgColor_radius_(self, frame, bg_color, radius=6.0):
        self = objc.super(SquircleBadgeView, self).initWithFrame_(frame)
        self.bg_color = bg_color
        self.radius = radius
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(radius)
        self.layer().setMasksToBounds_(True)
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, dirtyRect):
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), self.radius, self.radius)
        if self.bg_color:
            self.bg_color.setFill()
            path.fill()


class BatteryPillView(AppKit.NSView):
    """Sleek capsule battery progress bar matching macOS system aesthetics."""
    def initWithFrame_(self, frame):
        self = objc.super(BatteryPillView, self).initWithFrame_(frame)
        self.percentage = 0
        self.charging = False
        self.connected = False
        self.setWantsLayer_(True)
        return self

    def isFlipped(self):
        return True

    def setLevel_charging_connected_(self, lvl: int, chg: bool, conn: bool):
        self.percentage = max(0, min(100, lvl))
        self.charging = chg
        self.connected = conn
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirtyRect):
        bounds = self.bounds()
        radius = bounds.size.height / 2.0
        # Background track
        track = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, radius, radius)
        AppKit.NSColor.separatorColor().colorWithAlphaComponent_(0.25).setFill()
        track.fill()

        # Filled progress capsule
        if self.percentage > 0 and self.connected:
            fill_w = max(bounds.size.height, bounds.size.width * (self.percentage / 100.0))
            fill_rect = AppKit.NSMakeRect(0, 0, fill_w, bounds.size.height)
            fill_path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill_rect, radius, radius)
            if self.charging:
                AppKit.NSColor.systemGreenColor().setFill()
            elif self.percentage > 20:
                AppKit.NSColor.systemGreenColor().setFill()
            elif self.percentage > 10:
                AppKit.NSColor.systemOrangeColor().setFill()
            else:
                AppKit.NSColor.systemRedColor().setFill()
            fill_path.fill()


# ==============================================================================
# Main Menu Bar Application Delegate
# ==============================================================================
class BudsAirPodsApp(AppKit.NSObject):
    find_connected_supported_device = staticmethod(find_connected_supported_device)

    def init(self):
        self = objc.super(BudsAirPodsApp, self).init()
        if not self:
            return None

        # Check initial Bluetooth connection state
        matched_profile, matched_device = find_connected_supported_device()

        self.ble = NativeBudsBLEController.alloc().init()
        self.ble.delegate = self
        if matched_profile:
            self.ble.profile = matched_profile
            self.ble.device_name = matched_profile.name
            log(f"Active device bound: {matched_profile.name} [{matched_profile.model_code}]")

        self.dismiss_timer = None
        self.has_shown_connect_card = False
        self.is_noise_expanded = False

        # Setup native UI
        self.setup_status_bar()
        self.setup_popover()
        self.setup_context_menu()
        self.update_ui_state()

        # Start Unix domain socket IPC server
        self.ipc_server = BudsIPCServer(self.ble)
        self.ipc_server.start()

        # Initialize native IOBluetooth Audio Device Monitor inline
        self.bt_monitor = BluetoothAudioMonitor(
            on_connected=self.on_bluetooth_device_connected,
            on_disconnected=self.on_bluetooth_device_disconnected,
            auto_invoke_app=False
        )
        self.bt_monitor.start()

        if matched_profile:
            self.ble.attempt_fast_connect()
            self.trigger_connect_card()

        # Periodic refresh timer on main run loop
        self.refresh_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            30.0, self, "onPeriodicTimer:", None, True
        )
        return self

    def on_bluetooth_device_connected(self, device, profile, is_initial):
        if not profile:
            name = device.getName() if device else ""
            profile = match_supported_device(name)
            if not profile:
                return

        log(f"Native Bluetooth Audio Connected: {profile.name} (initial={is_initial})")

        # Invalidate/clear state address, handshake, and timeouts when switching or connecting a device
        if self.ble.device_name != profile.name or self.ble.state.device_name != profile.name:
            self.ble.state.address = ""
            self.ble.cancel_connection_timeout()
        self.ble._handshake_started = False
        self.ble.profile = profile
        self.ble.device_name = profile.name

        # Expand status item from 0px collapse
        self.status_item.setLength_(AppKit.NSVariableStatusItemLength)
        self._current_status_len = AppKit.NSVariableStatusItemLength

        # Trigger fast CoreBluetooth connection
        self.ble.attempt_fast_connect()
        self.update_ui_state()

        if not is_initial:
            self.has_shown_connect_card = False
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.trigger_connect_card()

    def on_bluetooth_device_disconnected(self, device, profile):
        dev_name = profile.name if profile else 'Device'
        log(f"Native Bluetooth Audio Disconnected: {dev_name}")
        self.has_shown_connect_card = False

        # Invalidate/clear connection timeout, handshake, and address
        self.ble.cancel_connection_timeout()
        self.ble._handshake_started = False
        self.ble.state.address = ""

        # Cancel BLE connection and stop any scans
        if self.ble.central and self.ble.is_scanning:
            try:
                self.ble.central.stopScan()
            except Exception:
                pass
            self.ble.is_scanning = False

        if self.ble.peripheral:
            try:
                self.ble.central.cancelPeripheralConnection_(self.ble.peripheral)
            except Exception:
                pass

        self.ble.peripheral = None
        self.ble.tx_char = None
        self.ble.rx_char = None
        self.ble.is_connected = False
        self.ble.is_connecting = False
        self.ble.status_message = "Disconnected"
        self.ble.state.current_noise_mode = ""

        for k in ["left", "right", "case", "single"]:
            if k in self.ble.battery:
                self.ble.battery[k]["connected"] = False

        self.update_ui_state()
        if self.popover and self.popover.isShown():
            self.popover.performClose_(None)

        # Dynamic collapse to 0px on disconnect (inline monitor stays active)
        if self.ble.hide_when_disconnected:
            self.status_item.setLength_(0.0)
            self._current_status_len = 0.0

        if "--exit-if-disconnected" in sys.argv:
            other_prof, _ = self.find_connected_supported_device()
            if not other_prof:
                log("Disconnected. Terminating as requested.")
                AppKit.NSApplication.sharedApplication().terminate_(None)

    def onPeriodicTimer_(self, _):
        if self.ble.is_connected:
            self.ble.refresh()

    def trigger_connect_card(self):
        if self.has_shown_connect_card:
            return
        self.has_shown_connect_card = True
        self.status_item.setLength_(AppKit.NSVariableStatusItemLength)
        self._current_status_len = AppKit.NSVariableStatusItemLength
        AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.15, self, "onDelayedShowConnectCard:", None, False
        )

    def onDelayedShowConnectCard_(self, _):
        self.show_connect_popup(auto_dismiss=4.0)

    def show_connect_popup(self, auto_dismiss: float = 4.0):
        btn = self.status_item.button()
        if btn and not self.popover.isShown():
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                btn.bounds(), btn, AppKit.NSRectEdgeMinY
            )
            if self.dismiss_timer:
                self.dismiss_timer.invalidate()
                self.dismiss_timer = None

            if auto_dismiss > 0:
                self.dismiss_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    auto_dismiss, self, "onAutoDismissTimer:", None, False
                )

    def onAutoDismissTimer_(self, _):
        if self.popover.isShown():
            self.popover.performClose_(None)
        self.dismiss_timer = None

    def cancel_auto_dismiss(self):
        if self.dismiss_timer:
            self.dismiss_timer.invalidate()
            self.dismiss_timer = None

    def setup_status_bar(self):
        self.status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        btn = self.status_item.button()
        btn.setTarget_(self)
        btn.setAction_("onStatusBarClicked:")
        btn.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)

        self.bar_icon = get_sf_symbol("airpodspro", 15.0, AppKit.NSFontWeightSemibold)
        if not self.bar_icon:
            self.bar_icon = get_sf_symbol("headphones", 15.0, AppKit.NSFontWeightSemibold)
        if self.bar_icon:
            self.bar_icon.setTemplate_(True)
            btn.setImage_(self.bar_icon)
            btn.setImagePosition_(AppKit.NSImageOnly)
            btn.setTitle_("")

    def onStatusBarClicked_(self, sender):
        self.cancel_auto_dismiss()
        event = AppKit.NSApp.currentEvent()
        if event and (event.type() == AppKit.NSEventTypeRightMouseUp or (event.modifierFlags() & AppKit.NSEventModifierFlagControl)):
            self.status_item.popUpStatusItemMenu_(self.context_menu)
        else:
            if self.popover.isShown():
                self.popover.performClose_(sender)
            else:
                if not self.ble.is_connected:
                    self.ble.attempt_fast_connect()
                btn = self.status_item.button()
                self.popover.showRelativeToRect_ofView_preferredEdge_(
                    btn.bounds(), btn, AppKit.NSRectEdgeMinY
                )

    def setup_popover(self):
        self.popover = AppKit.NSPopover.alloc().init()
        self.popover.setBehavior_(AppKit.NSPopoverBehaviorTransient)
        self.popover.setAnimates_(True)

        popover_width = 330.0
        popover_height = 540.0

        self.content_view = FlippedVisualEffectView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, popover_width, popover_height)
        )
        self.content_view.setMaterial_(AppKit.NSVisualEffectMaterialPopover)
        self.content_view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        self.content_view.setState_(AppKit.NSVisualEffectStateActive)

        self.setup_popover_subviews()

        vc = AppKit.NSViewController.alloc().init()
        vc.setView_(self.content_view)
        self.popover.setContentViewController_(vc)

    def create_section_label(self, text: str, x: float, y: float) -> AppKit.NSTextField:
        lbl = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, 280.0, 14.0))
        lbl.setStringValue_(text)
        lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(10.5, AppKit.NSFontWeightBold))
        lbl.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        return lbl

    def create_footer_button(self, title: str, sym_name: str, x: float, y: float, w: float, action_name: str) -> AppKit.NSButton:
        btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(x, y, w, 28.0))
        btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn.setTitle_(title)
        btn.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.5, AppKit.NSFontWeightMedium))
        img = get_sf_symbol(sym_name, 11.5, AppKit.NSFontWeightMedium)
        if img:
            btn.setImage_(img)
            btn.setImagePosition_(AppKit.NSImageLeading)
        btn.setTarget_(self)
        btn.setAction_(action_name)
        return btn

    def setup_popover_subviews(self):
        root = self.content_view
        popover_width = 330.0
        pad = 16.0
        content_w = popover_width - (pad * 2.0)  # 298.0
        y = 16.0

        # 1. Header Card (Device Icon Badge + Name + Status Dot + Connect/Disconnect Button)
        header_view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 42.0))

        # Device Icon Squircle Badge
        icon_bg = SquircleBadgeView.alloc().initWithFrame_bgColor_radius_(
            AppKit.NSMakeRect(0, 1.0, 40.0, 40.0),
            AppKit.NSColor.systemBlueColor().colorWithAlphaComponent_(0.12),
            10.0
        )
        self.header_icon = AppKit.NSImageView.alloc().initWithFrame_(AppKit.NSMakeRect(8.0, 8.0, 24.0, 24.0))
        self.header_icon.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
        icon_img = get_sf_symbol("airpodspro", 20.0, AppKit.NSFontWeightSemibold)
        if not icon_img:
            icon_img = get_sf_symbol("headphones", 20.0, AppKit.NSFontWeightSemibold)
        if icon_img:
            self.header_icon.setImage_(icon_img)
            self.header_icon.setContentTintColor_(AppKit.NSColor.systemBlueColor())
        icon_bg.addSubview_(self.header_icon)
        header_view.addSubview_(icon_bg)

        # Device Title Label
        self.title_label = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(48.0, 2.0, content_w - 140.0, 20.0))
        self.title_label.setStringValue_(self.ble.device_name)
        self.title_label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(14.0, AppKit.NSFontWeightBold))
        self.title_label.setTextColor_(AppKit.NSColor.labelColor())
        self.title_label.setBezeled_(False)
        self.title_label.setDrawsBackground_(False)
        self.title_label.setEditable_(False)
        self.title_label.setSelectable_(False)
        header_view.addSubview_(self.title_label)

        # Status Dot & Text (● Connected / Disconnected)
        self.status_label = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(48.0, 22.0, content_w - 140.0, 18.0))
        self.status_label.setStringValue_("● Connected")
        self.status_label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.5, AppKit.NSFontWeightMedium))
        self.status_label.setTextColor_(AppKit.NSColor.systemGreenColor())
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        self.status_label.setSelectable_(False)
        header_view.addSubview_(self.status_label)

        # Connect / Disconnect button (Pill style)
        self.connect_btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(content_w - 86.0, 8.0, 86.0, 26.0))
        self.connect_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.connect_btn.setTitle_("Disconnect")
        self.connect_btn.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightMedium))
        self.connect_btn.setTarget_(self)
        self.connect_btn.setAction_("onConnectToggleClicked:")
        header_view.addSubview_(self.connect_btn)

        root.addSubview_(header_view)
        y += 50.0

        # 2. AirPods 3-Column Battery Card (Left / Right / Case)
        card_h = 96.0
        self.battery_card = RoundedCardView.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, card_h))
        col_w = content_w / 3.0

        self.battery_ui = {}
        items_meta = [
            ("left", "airpod.gen3.left", "Left", 0),
            ("right", "airpod.gen3.right", "Right", 1),
            ("case", "airpodspro.chargingcase.wireless", "Case", 2)
        ]

        for key, sym_name, title, col_idx in items_meta:
            col_x = col_idx * col_w

            # Device SF Symbol
            iv = AppKit.NSImageView.alloc().initWithFrame_(AppKit.NSMakeRect(col_x + (col_w - 24.0) / 2.0, 8.0, 24.0, 24.0))
            iv.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
            s_img = get_sf_symbol(sym_name, 17.0, AppKit.NSFontWeightMedium)
            if s_img:
                iv.setImage_(s_img)
                iv.setContentTintColor_(AppKit.NSColor.secondaryLabelColor())
            self.battery_card.addSubview_(iv)

            # Percentage Label (e.g. "100%")
            pct_lbl = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(col_x, 36.0, col_w, 18.0))
            pct_lbl.setStringValue_("--%")
            pct_lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(14.0, AppKit.NSFontWeightBold))
            pct_lbl.setTextColor_(AppKit.NSColor.labelColor())
            pct_lbl.setAlignment_(AppKit.NSTextAlignmentCenter)
            pct_lbl.setBezeled_(False)
            pct_lbl.setDrawsBackground_(False)
            pct_lbl.setEditable_(False)
            pct_lbl.setSelectable_(False)
            self.battery_card.addSubview_(pct_lbl)

            # Battery Capsule Mini Pill Bar
            pill = BatteryPillView.alloc().initWithFrame_(AppKit.NSMakeRect(col_x + (col_w - 46.0) / 2.0, 58.0, 46.0, 7.0))
            self.battery_card.addSubview_(pill)

            # Subtitle Caption (e.g. "Left", "Right", "Case")
            sub_lbl = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(col_x, 70.0, col_w, 16.0))
            sub_lbl.setStringValue_(title)
            sub_lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightMedium))
            sub_lbl.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            sub_lbl.setAlignment_(AppKit.NSTextAlignmentCenter)
            sub_lbl.setBezeled_(False)
            sub_lbl.setDrawsBackground_(False)
            sub_lbl.setEditable_(False)
            sub_lbl.setSelectable_(False)
            self.battery_card.addSubview_(sub_lbl)

            self.battery_ui[key] = {"pct": pct_lbl, "pill": pill, "icon": iv, "sub": sub_lbl}

        root.addSubview_(self.battery_card)
        y += card_h + 12.0

        # 3. Noise Control Section (AirPods Pro Style)
        lbl_nc = self.create_section_label("NOISE CONTROL", pad, y)
        root.addSubview_(lbl_nc)
        y += 18.0

        self.noise_seg = AppKit.NSSegmentedControl.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 28.0))
        self.noise_seg.setSegmentCount_(3)
        self.noise_seg.setSegmentStyle_(AppKit.NSSegmentStyleRounded)
        self.noise_seg.setLabel_forSegment_("Noise Cancellation", 0)
        self.noise_seg.setLabel_forSegment_("Off", 1)
        self.noise_seg.setLabel_forSegment_("Transparency", 2)

        anc_img = get_sf_symbol("waveform.path.badge.minus", 12.0)
        off_img = get_sf_symbol("waveform.slash", 12.0)
        trans_img = get_sf_symbol("waveform.path", 12.0)
        if anc_img: self.noise_seg.setImage_forSegment_(anc_img, 0)
        if off_img: self.noise_seg.setImage_forSegment_(off_img, 1)
        if trans_img: self.noise_seg.setImage_forSegment_(trans_img, 2)

        self.noise_seg.setTarget_(self)
        self.noise_seg.setAction_("onNoiseSegChanged:")
        root.addSubview_(self.noise_seg)
        y += 32.0

        # Sub-selector for ANC level: [ Auto | Low | Moderate | High ]
        self.anc_level_seg = AppKit.NSSegmentedControl.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 24.0))
        self.anc_level_seg.setSegmentCount_(4)
        self.anc_level_seg.setSegmentStyle_(AppKit.NSSegmentStyleRounded)
        self.anc_level_seg.setLabel_forSegment_("Auto", 0)
        self.anc_level_seg.setLabel_forSegment_("Low", 1)
        self.anc_level_seg.setLabel_forSegment_("Moderate", 2)
        self.anc_level_seg.setLabel_forSegment_("High", 3)
        self.anc_level_seg.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular))
        self.anc_level_seg.setTarget_(self)
        self.anc_level_seg.setAction_("onAncLevelSegChanged:")
        root.addSubview_(self.anc_level_seg)
        y += 30.0

        # 4. Spatial Audio Section
        lbl_sa = self.create_section_label("SPATIAL AUDIO", pad, y)
        root.addSubview_(lbl_sa)
        y += 18.0

        self.spatial_seg = AppKit.NSSegmentedControl.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 26.0))
        self.spatial_seg.setSegmentCount_(2)
        self.spatial_seg.setSegmentStyle_(AppKit.NSSegmentStyleRounded)
        self.spatial_seg.setLabel_forSegment_("Off", 0)
        self.spatial_seg.setLabel_forSegment_("Spatial Audio", 1)
        spk_img = get_sf_symbol("sparkles", 12.0)
        if spk_img: self.spatial_seg.setImage_forSegment_(spk_img, 1)
        self.spatial_seg.setTarget_(self)
        self.spatial_seg.setAction_("onSpatialSegChanged:")
        root.addSubview_(self.spatial_seg)
        y += 32.0

        # 5. Audio Enhancements Group (macOS System Settings Style Card)
        lbl_enh = self.create_section_label("AUDIO ENHANCEMENTS", pad, y)
        root.addSubview_(lbl_enh)
        y += 18.0

        enh_card = RoundedCardView.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 136.0))
        self.enh_switches = {}

        toggles_data = [
            (FEATURE_BASS_ENGINE, "speaker.wave.3", "BassWave™ (Dynamic Bass)", 0, AppKit.NSColor.systemPurpleColor()),
            (FEATURE_GAME_MODE, "gamecontroller", "Game Mode (Low Latency)", 1, AppKit.NSColor.systemOrangeColor()),
            (FEATURE_IN_EAR, "ear", "In-Ear Detection (Auto-Pause)", 2, AppKit.NSColor.systemGreenColor()),
            (FEATURE_DUAL_CONNECT, "antenna.radiowaves.left.and.right", "Dual Device Connection", 3, AppKit.NSColor.systemBlueColor()),
        ]

        row_h = 34.0
        for fid, sym, text, idx, badge_color in toggles_data:
            ry = idx * row_h

            # macOS System Settings Colored Squircle Badge
            badge = SquircleBadgeView.alloc().initWithFrame_bgColor_radius_(
                AppKit.NSMakeRect(10.0, ry + 5.0, 24.0, 24.0),
                badge_color,
                6.0
            )
            b_iv = AppKit.NSImageView.alloc().initWithFrame_(AppKit.NSMakeRect(4.0, 4.0, 16.0, 16.0))
            b_iv.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
            b_img = get_sf_symbol(sym, 11.5, AppKit.NSFontWeightSemibold)
            if b_img:
                b_iv.setImage_(b_img)
                b_iv.setContentTintColor_(AppKit.NSColor.whiteColor())
            badge.addSubview_(b_iv)
            enh_card.addSubview_(badge)

            # Row Label
            row_lbl = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(42.0, ry + 8.0, content_w - 94.0, 18.0))
            row_lbl.setStringValue_(text)
            row_lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(12.0, AppKit.NSFontWeightRegular))
            row_lbl.setTextColor_(AppKit.NSColor.labelColor())
            row_lbl.setBezeled_(False)
            row_lbl.setDrawsBackground_(False)
            row_lbl.setEditable_(False)
            row_lbl.setSelectable_(False)
            enh_card.addSubview_(row_lbl)

            # Switch
            sw = AppKit.NSSwitch.alloc().initWithFrame_(AppKit.NSMakeRect(content_w - 46.0, ry + 7.0, 38.0, 20.0))
            sw.setTarget_(self)
            sw.setAction_("onFeatureSwitchToggled:")
            sw.setTag_(fid)
            enh_card.addSubview_(sw)
            self.enh_switches[fid] = sw

            # Inset Hairline Divider between rows
            if idx < 3:
                sep_line = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(42.0, ry + 33.0, content_w - 42.0, 1.0))
                sep_line.setBoxType_(AppKit.NSBoxSeparator)
                enh_card.addSubview_(sep_line)

        root.addSubview_(enh_card)
        y += 144.0

        # 6. Sound Master EQ Presets
        lbl_eq = self.create_section_label("SOUND MASTER EQ", pad, y)
        root.addSubview_(lbl_eq)
        y += 18.0

        self.eq_seg = AppKit.NSSegmentedControl.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 24.0))
        self.eq_seg.setSegmentCount_(4)
        self.eq_seg.setSegmentStyle_(AppKit.NSSegmentStyleRounded)
        self.eq_seg.setLabel_forSegment_("Balanced", 0)
        self.eq_seg.setLabel_forSegment_("Bass", 1)
        self.eq_seg.setLabel_forSegment_("Clear", 2)
        self.eq_seg.setLabel_forSegment_("Bold", 3)
        self.eq_seg.setFont_(AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightRegular))
        self.eq_seg.setTarget_(self)
        self.eq_seg.setAction_("onEqSegChanged:")
        root.addSubview_(self.eq_seg)
        y += 32.0

        # 7. Symmetrical Footer Bar (Refresh, Quit) - Settings removed as all controls are in dropdown
        sep = AppKit.NSBox.alloc().initWithFrame_(AppKit.NSMakeRect(pad, y, content_w, 1.0))
        sep.setBoxType_(AppKit.NSBoxSeparator)
        root.addSubview_(sep)
        y += 8.0

        footer_w = (content_w - 10.0) / 2.0
        self.btn_refresh = self.create_footer_button("Refresh", "arrow.clockwise", pad, y, footer_w, "onRefreshClicked:")
        root.addSubview_(self.btn_refresh)

        self.btn_quit = self.create_footer_button("Quit", "power", pad + footer_w + 10.0, y, footer_w, "onQuitClicked:")
        root.addSubview_(self.btn_quit)
        y += 34.0

        total_h = y + 8.0
        self.content_view.setFrameSize_(Foundation.NSMakeSize(popover_width, total_h))
        self.popover.setContentSize_(Foundation.NSMakeSize(popover_width, total_h))

    def setup_context_menu(self):
        self.context_menu = AppKit.NSMenu.alloc().initWithTitle_("Buds Context Menu")

        self.ctx_device_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            self.ble.device_name, None, ""
        )
        self.ctx_device_item.setEnabled_(False)
        self.context_menu.addItem_(self.ctx_device_item)

        self.ctx_status_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Disconnected", None, ""
        )
        self.ctx_status_item.setEnabled_(False)
        self.context_menu.addItem_(self.ctx_status_item)

        self.context_menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Noise Control Submenu
        anc_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Noise Control", None, "")
        self.anc_submenu = AppKit.NSMenu.alloc().initWithTitle_("Noise Control")
        for mode in PRIMARY_NOISE_MODES:
            it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                mode, "onCtxPrimaryModeClicked:", ""
            )
            it.setTarget_(self)
            self.anc_submenu.addItem_(it)
        self.anc_submenu.addItem_(AppKit.NSMenuItem.separatorItem())
        for mode in ANC_MODES:
            it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"ANC: {mode}", "onCtxAncLevelClicked:", ""
            )
            it.setTarget_(self)
            self.anc_submenu.addItem_(it)
        anc_item.setSubmenu_(self.anc_submenu)
        self.context_menu.addItem_(anc_item)

        # EQ Submenu
        eq_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Sound Master EQ", None, "")
        self.eq_submenu = AppKit.NSMenu.alloc().initWithTitle_("EQ")
        for eq in EQ_PRESETS.keys():
            it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                eq, "onCtxEqClicked:", ""
            )
            it.setTarget_(self)
            self.eq_submenu.addItem_(it)
        eq_item.setSubmenu_(self.eq_submenu)
        self.context_menu.addItem_(eq_item)

        self.context_menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Feature Toggles
        for fid, fname in [
            (FEATURE_SPATIAL_AUDIO, "Spatial Audio"),
            (FEATURE_GAME_MODE, "Game Mode"),
            (FEATURE_BASS_ENGINE, "BassWave™"),
            (FEATURE_IN_EAR, "In-Ear Detection"),
            (FEATURE_DUAL_CONNECT, "Dual Connection"),
        ]:
            it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                fname, "onCtxFeatureClicked:", ""
            )
            it.setTarget_(self)
            it.setTag_(fid)
            self.context_menu.addItem_(it)

        self.context_menu.addItem_(AppKit.NSMenuItem.separatorItem())

        quit_it = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit OnePlus Buds", "onQuitClicked:", "q"
        )
        quit_it.setTarget_(self)
        self.context_menu.addItem_(quit_it)

    def update_ui_state(self):
        b = self.ble.battery
        l_info = b.get("left", {})
        r_info = b.get("right", {})
        c_info = b.get("case", {})

        l_lvl = l_info.get("level", 0) if isinstance(l_info, dict) else (l_info if isinstance(l_info, int) else 0)
        l_chg = l_info.get("charging", False) if isinstance(l_info, dict) else False
        r_lvl = r_info.get("level", 0) if isinstance(r_info, dict) else (r_info if isinstance(r_info, int) else 0)
        r_chg = r_info.get("charging", False) if isinstance(r_info, dict) else False
        c_lvl = c_info.get("level", 0) if isinstance(c_info, dict) else (c_info if isinstance(c_info, int) else 0)
        c_chg = c_info.get("charging", False) if isinstance(c_info, dict) else False

        l_conn = l_info.get("connected", False) if isinstance(l_info, dict) else (l_lvl > 0)
        r_conn = r_info.get("connected", False) if isinstance(r_info, dict) else (r_lvl > 0)
        c_conn = c_info.get("connected", False) if isinstance(c_info, dict) else (c_lvl > 0)

        # 1. Menu Bar Dynamic Length and Collapse
        btn = self.status_item.button()
        is_active = self.ble.is_connected or self.ble.is_connecting
        target_len = 0.0 if (self.ble.hide_when_disconnected and not is_active) else AppKit.NSVariableStatusItemLength
        if getattr(self, "_current_status_len", None) != target_len:
            self.status_item.setLength_(target_len)
            self._current_status_len = target_len

        if self.ble.hide_when_disconnected and not is_active:
            btn.setTitle_("")
            btn.setImage_(None)
            if self.popover.isShown():
                self.popover.performClose_(None)
        else:
            if getattr(self, "bar_icon", None):
                btn.setImage_(self.bar_icon)
            btn.setTitle_("")
            btn.setImagePosition_(AppKit.NSImageOnly)

        tooltip = f"{self.ble.device_name} • L: {l_lvl}% | R: {r_lvl}% | Case: {c_lvl}% ({self.ble.status_message})"
        btn.setToolTip_(tooltip)

        # 2. Header
        self.title_label.setStringValue_(self.ble.device_name)
        if self.ble.is_connected:
            self.status_label.setStringValue_("● Connected")
            self.status_label.setTextColor_(AppKit.NSColor.systemGreenColor())
            self.connect_btn.setTitle_("Disconnect")
        elif self.ble.is_connecting:
            self.status_label.setStringValue_(f"● {self.ble.status_message or 'Connecting...'}")
            self.status_label.setTextColor_(AppKit.NSColor.systemOrangeColor())
            self.connect_btn.setTitle_("Connecting")
        else:
            self.status_label.setStringValue_("● Disconnected")
            self.status_label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
            self.connect_btn.setTitle_("Connect")

        # 3. 3-Column Battery Card
        prof = self.ble.profile
        is_neckband = prof.is_neckband if prof else False

        if is_neckband:
            single = b.get("single") or b.get("left") or {}
            s_lvl = single.get("level", 0) if isinstance(single, dict) else (single if isinstance(single, int) else 0)
            s_chg = single.get("charging", False) if isinstance(single, dict) else False
            s_conn = self.ble.is_connected

            ui_l = self.battery_ui.get("left")
            if ui_l:
                ui_l["pct"].setStringValue_(f"{s_lvl}%{' ⚡' if s_chg else ''}" if s_conn and s_lvl > 0 else "--%")
                ui_l["pill"].setLevel_charging_connected_(s_lvl, s_chg, s_conn)
                ui_l["sub"].setStringValue_("Battery")
                ui_l["icon"].setContentTintColor_(AppKit.NSColor.systemGreenColor() if s_chg else AppKit.NSColor.secondaryLabelColor())

            for k in ["right", "case"]:
                ui = self.battery_ui.get(k)
                if ui:
                    ui["pct"].setStringValue_("--%")
                    ui["pill"].setLevel_charging_connected_(0, False, False)
                    ui["icon"].setContentTintColor_(AppKit.NSColor.secondaryLabelColor())
        else:
            for key, lvl, chg, conn in [("left", l_lvl, l_chg, l_conn and self.ble.is_connected),
                                        ("right", r_lvl, r_chg, r_conn and self.ble.is_connected),
                                        ("case", c_lvl, c_chg, c_conn and self.ble.is_connected)]:
                ui = self.battery_ui.get(key)
                if ui:
                    bolt = " ⚡" if chg else ""
                    ui["pct"].setStringValue_(f"{lvl}%{bolt}" if (conn and lvl > 0) else "--%")
                    ui["pill"].setLevel_charging_connected_(lvl, chg, conn)
                    if chg:
                        ui["icon"].setContentTintColor_(AppKit.NSColor.systemGreenColor())
                    else:
                        ui["icon"].setContentTintColor_(AppKit.NSColor.secondaryLabelColor())

        # 4. Noise Control Segments
        cur_prim = self.ble.last_primary_mode
        cur_anc = self.ble.last_anc_mode
        cur_noise = self.ble.current_noise_mode

        if cur_prim == "Noise Cancellation" or cur_noise in ["Auto", "Low", "Moderate", "High", "Smart ANC", "Depth ANC", "Mild ANC"]:
            self.noise_seg.setSelectedSegment_(0)
            self.anc_level_seg.setEnabled_(True)
            anc_map = {"Auto": 0, "Low": 1, "Moderate": 2, "High": 3, "Smart ANC": 0, "Depth ANC": 3, "Mild ANC": 1}
            active_level = cur_anc or cur_noise
            if active_level in anc_map:
                self.anc_level_seg.setSelectedSegment_(anc_map[active_level])
        elif cur_prim == "Off" or cur_noise == "Off":
            self.noise_seg.setSelectedSegment_(1)
            self.anc_level_seg.setEnabled_(False)
        elif cur_prim == "Transparency" or cur_noise == "Transparency":
            self.noise_seg.setSelectedSegment_(2)
            self.anc_level_seg.setEnabled_(False)

        # 5. Spatial Audio Segment
        sa_on = self.ble.features.get(FEATURE_SPATIAL_AUDIO, False)
        self.spatial_seg.setSelectedSegment_(1 if sa_on else 0)

        # 6. Audio Enhancement Switches
        feats = self.ble.features
        for fid, sw in self.enh_switches.items():
            f_val = feats.get(fid, False)
            sw.setState_(AppKit.NSControlStateValueOn if f_val else AppKit.NSControlStateValueOff)

        # 7. Sound Master EQ
        cur_eq = self.ble.current_eq
        eq_map = {"Balanced": 0, "Bass": 1, "Clear": 2, "Bold": 3}
        if cur_eq in eq_map:
            self.eq_seg.setSelectedSegment_(eq_map[cur_eq])

        # 8. Context Menu Updates
        self.ctx_device_item.setTitle_(f"{self.ble.device_name}" + (f" ({prof.category_title})" if prof else ""))
        self.ctx_status_item.setTitle_(f"Status: {self.ble.status_message}")

        for it in self.anc_submenu.itemArray():
            title = it.title()
            if title in PRIMARY_NOISE_MODES:
                it.setState_(AppKit.NSControlStateValueOn if title == self.ble.last_primary_mode else AppKit.NSControlStateValueOff)
            elif title.startswith("ANC: "):
                sub_name = title.replace("ANC: ", "")
                it.setState_(AppKit.NSControlStateValueOn if (self.ble.last_primary_mode == "Noise Cancellation" and sub_name == self.ble.last_anc_mode) else AppKit.NSControlStateValueOff)

        for it in self.eq_submenu.itemArray():
            it.setState_(AppKit.NSControlStateValueOn if it.title() == self.ble.current_eq else AppKit.NSControlStateValueOff)

        for it in self.context_menu.itemArray():
            fid = it.tag()
            if fid in feats:
                it.setState_(AppKit.NSControlStateValueOn if feats.get(fid, False) else AppKit.NSControlStateValueOff)

        # Broadcast state update to attached CLI over IPC
        if getattr(self, "ipc_server", None):
            self.ipc_server.broadcast_state()

    # User Actions
    def onConnectToggleClicked_(self, sender):
        self.cancel_auto_dismiss()
        if self.ble.is_connected:
            self.ble.disconnect()
        else:
            self.ble.attempt_fast_connect()

    def onNoiseSegChanged_(self, sender):
        self.cancel_auto_dismiss()
        idx = sender.selectedSegment()
        if idx == 0:
            self.anc_level_seg.setEnabled_(True)
            sub_idx = self.anc_level_seg.selectedSegment()
            sub_map = {0: "Auto", 1: "Low", 2: "Moderate", 3: "High"}
            mode = sub_map.get(sub_idx, "Auto")
            self.ble.set_primary_mode("Noise Cancellation")
            self.ble.set_noise_mode(mode)
        elif idx == 1:
            self.anc_level_seg.setEnabled_(False)
            self.ble.set_primary_mode("Off")
            self.ble.set_noise_mode("Off")
        else:
            self.anc_level_seg.setEnabled_(False)
            self.ble.set_primary_mode("Transparency")
            self.ble.set_noise_mode("Transparency")

    def onAncLevelSegChanged_(self, sender):
        self.cancel_auto_dismiss()
        idx = sender.selectedSegment()
        sub_map = {0: "Auto", 1: "Low", 2: "Moderate", 3: "High"}
        mode = sub_map.get(idx, "Auto")
        self.noise_seg.setSelectedSegment_(0)
        self.anc_level_seg.setEnabled_(True)
        self.ble.set_primary_mode("Noise Cancellation")
        self.ble.set_noise_mode(mode)

    def onSpatialSegChanged_(self, sender):
        self.cancel_auto_dismiss()
        idx = sender.selectedSegment()
        enable = (idx == 1)
        self.ble.set_feature(FEATURE_SPATIAL_AUDIO, enable)

    def onFeatureSwitchToggled_(self, sender):
        self.cancel_auto_dismiss()
        fid = sender.tag()
        enable = (sender.state() == AppKit.NSControlStateValueOn)
        self.ble.set_feature(fid, enable)

    def onEqSegChanged_(self, sender):
        self.cancel_auto_dismiss()
        idx = sender.selectedSegment()
        eq_map = {0: "Balanced", 1: "Bass", 2: "Clear", 3: "Bold"}
        if idx in eq_map:
            self.ble.set_eq(eq_map[idx])

    def onRefreshClicked_(self, _):
        self.cancel_auto_dismiss()
        self.ble.refresh()

    def onCtxPrimaryModeClicked_(self, sender):
        self.ble.set_primary_mode(sender.title())

    def onCtxAncLevelClicked_(self, sender):
        sub_name = sender.title().replace("ANC: ", "")
        self.ble.set_noise_mode(sub_name)

    def onCtxFeatureClicked_(self, sender):
        fid = sender.tag()
        cur_val = self.ble.features.get(fid, False)
        self.ble.set_feature(fid, not cur_val)

    def onCtxEqClicked_(self, sender):
        self.ble.set_eq(sender.title())

    def onDisconnectClicked_(self, _):
        self.cancel_auto_dismiss()
        self.ble.disconnect()

    def onQuitClicked_(self, _):
        if getattr(self, "ipc_server", None):
            self.ipc_server.stop()
        AppKit.NSApplication.sharedApplication().terminate_(None)



def main():
    import fcntl
    lock_file = "/tmp/oneplus_buds_menubar.lock"
    try:
        lock_fd = open(lock_file, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        log("Menu bar agent is already running.")
        sys.exit(0)

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    delegate = BudsAirPodsApp.alloc().init()
    if not delegate:
        sys.exit(0)
    app.setDelegate_(delegate)

    app.run()


if __name__ == "__main__":
    main()
