#!/usr/bin/env python3
"""
Bleak / AsyncIO BLE Transport for OnePlus / OPPO / Realme Earbuds.
Used for standalone CLI and GUI sessions when the native menu bar agent is not running.
"""

import os
import sys
import asyncio
from typing import Optional, List, Dict, Any, Callable
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from core.protocol import (
    SERVICE_UUID_V1, SERVICE_UUID_V2, TX_CHAR_V1, RX_CHAR_V1,
    TX_CHAR_LEGACY, RX_CHAR_LEGACY
)
from core.ble_controller import BaseTransport, BaseBudsController
from device_manager import is_supported_device, match_supported_device, get_device_profile


async def discover_supported_earbuds(timeout: float = 4.0) -> List[BLEDevice]:
    """Scans for nearby Bluetooth Low Energy earbuds matching the 82-model catalog."""
    discovered = []

    def detection_callback(device, advertisement_data):
        name = device.name or advertisement_data.local_name
        if name and is_supported_device(name):
            if not any(d.address == device.address for d in discovered):
                discovered.append(device)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return discovered


class BleakTransport(BaseTransport):
    """
    Asynchronous BLE Transport using Bleak.
    """
    def __init__(self, controller: BaseBudsController, address: Optional[str] = None):
        self.controller = controller
        self.target_address = address
        self.client: Optional[BleakClient] = None
        self.rx_char_uuid: Optional[str] = None
        self.tx_char_uuid: Optional[str] = None
        self.ack_events: Dict[int, asyncio.Event] = {}
        self.is_connecting = False

    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    def send_bytes(self, data: bytearray) -> bool:
        if not self.is_connected() or not self.tx_char_uuid:
            return False
        # Asynchronously schedule write on the current or running loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.async_send_bytes(data))
            return True
        except RuntimeError:
            return False

    async def async_send_bytes(self, data: bytearray) -> bool:
        if not self.client or not self.client.is_connected or not self.tx_char_uuid:
            return False
        try:
            await self.client.write_gatt_char(self.tx_char_uuid, data, response=False)
            return True
        except Exception as e:
            print(f"[BleakTransport] Write error: {e}", file=sys.stderr)
            return False

    async def send_command_wait_ack(self, pkt: bytearray, expected_cmd_id: int, timeout: float = 2.0) -> bool:
        """Sends a packet and waits for expected ACK command ID."""
        event = asyncio.Event()
        self.ack_events[expected_cmd_id] = event
        if not await self.async_send_bytes(pkt):
            self.ack_events.pop(expected_cmd_id, None)
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self.ack_events.pop(expected_cmd_id, None)

    def _on_ble_notification(self, handle: int, data: bytearray):
        cmd_id = self.controller.parse_notification(data)
        if cmd_id is not None and cmd_id in self.ack_events:
            self.ack_events[cmd_id].set()

    async def connect(self, target_address: Optional[str] = None, target_name: Optional[str] = None) -> bool:
        if self.is_connected():
            return True
        if self.is_connecting:
            return False

        self.is_connecting = True
        self.controller.state.is_connecting = True
        self.controller.state.status_message = "Connecting..."
        self.controller.notify_ui()

        addr = target_address or self.target_address or self.controller.state.address

        try:
            if not addr:
                print("[BleakTransport] Scanning for nearby supported earbuds...")
                devices = await discover_supported_earbuds(timeout=3.5)
                if not devices:
                    print("[BleakTransport] No supported earbuds found nearby.")
                    self.controller.state.is_connecting = False
                    self.controller.state.status_message = "Disconnected"
                    self.controller.notify_ui()
                    self.is_connecting = False
                    return False
                selected = devices[0]
                addr = selected.address
                target_name = selected.name or target_name

            self.target_address = addr
            self.controller.state.address = addr

            if target_name:
                self.controller.state.device_name = target_name
                prof = match_supported_device(target_name)
                if prof:
                    self.controller.state.profile = prof

            print(f"[BleakTransport] Connecting to {self.controller.state.device_name} ({addr})...")
            self.client = BleakClient(addr, disconnected_callback=self._on_disconnected)
            await self.client.connect()

            if not self.client.is_connected:
                print(f"[BleakTransport] Failed to connect to {addr}")
                self.controller.state.is_connecting = False
                self.controller.state.status_message = "Disconnected"
                self.controller.notify_ui()
                self.is_connecting = False
                return False

            # Discover Characteristics
            rx_char = None
            tx_char = None
            for service in self.client.services:
                for char in service.characteristics:
                    c_uuid = char.uuid.upper()
                    if c_uuid in [RX_CHAR_V1.upper(), RX_CHAR_LEGACY.upper()] or "NOTIFY" in char.properties:
                        if not rx_char and ("NOTIFY" in char.properties or "INDICATE" in char.properties):
                            rx_char = char.uuid
                    if c_uuid in [TX_CHAR_V1.upper(), TX_CHAR_LEGACY.upper()] or "WRITE" in "".join(char.properties):
                        if not tx_char and ("WRITE" in char.properties or "WRITE-WITHOUT-RESPONSE" in char.properties):
                            tx_char = char.uuid

            self.rx_char_uuid = rx_char or RX_CHAR_V1
            self.tx_char_uuid = tx_char or TX_CHAR_V1

            # Subscribe to RX notifications
            try:
                await self.client.start_notify(self.rx_char_uuid, self._on_ble_notification)
            except Exception as e:
                print(f"[BleakTransport] Warning subscribing to notifications: {e}")

            self.controller.set_transport(self)
            self.controller.state.is_connected = True
            self.controller.state.is_connecting = False
            self.controller.state.status_message = "Connected"
            self.controller.notify_ui()

            # Execute session handshake sequence
            await asyncio.sleep(0.15)
            await self.async_send_bytes(self.controller.protocol.build_hello())
            await asyncio.sleep(0.3)
            await self.async_send_bytes(self.controller.protocol.build_register())
            await asyncio.sleep(0.35)
            self.controller.refresh()

            self.is_connecting = False
            return True

        except Exception as e:
            print(f"[BleakTransport] Connection error: {e}", file=sys.stderr)
            self.controller.state.is_connected = False
            self.controller.state.is_connecting = False
            self.controller.state.status_message = "Disconnected"
            self.controller.notify_ui()
            self.is_connecting = False
            return False

    def _on_disconnected(self, client):
        print("[BleakTransport] Peripheral disconnected.")
        self.controller.state.is_connected = False
        self.controller.state.is_connecting = False
        self.controller.state.status_message = "Disconnected"
        for k in ["left", "right", "case", "single"]:
            if k in self.controller.state.battery:
                self.controller.state.battery[k]["connected"] = False
        self.controller.state.save_cache()
        self.controller.notify_ui()

    async def disconnect(self):
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.controller.state.is_connected = False
        self.controller.state.is_connecting = False
        self.controller.state.status_message = "Disconnected"
        self.controller.notify_ui()
