#!/usr/bin/env python3
"""
bluetooth_monitor.py
Background Bluetooth connection listener for OnePlus Buds macOS Companion App.
Monitors system-level IOBluetooth audio device connections and triggers OnePlus Buds.app.
"""

import os
import sys
import time
import socket
import json
import threading
import subprocess
from typing import Optional, Dict, Any, List, Callable

# Ensure current directory and unpacked workspace are at front of sys.path
_this_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
_workspace = '/Users/digvijayasatapathy/HeyMelody_unpacked'
for d in [_this_dir, _workspace]:
    if d and os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)

import objc
import AppKit
import Foundation

from device_manager import (
    match_supported_device, get_device_profile, is_supported_device, DeviceProfile, DEFAULT_PROFILE
)

# Constants per specification
APP_PATH = '/Applications/OnePlus Buds.app'
APP_BUNDLE_ID = 'com.oneplus.buds'
FALLBACK_BUNDLE_ID = 'com.oneplus.buds.menubar'
IPC_SOCKET_PATH = '/tmp/oneplus_buds_ipc.sock'

# Dynamically load IOBluetooth.framework
IOBLUETOOTH_PATH = '/System/Library/Frameworks/IOBluetooth.framework'
try:
    objc.loadBundle('IOBluetooth', globals(), bundle_path=IOBLUETOOTH_PATH)
    IOBluetoothDevice = objc.lookUpClass('IOBluetoothDevice')
    IOBluetoothDeviceNotification = objc.lookUpClass('IOBluetoothUserNotification')
except Exception as e:
    print(f'[BluetoothMonitor] Warning: Could not load IOBluetooth.framework: {e}')
    IOBluetoothDevice = None
    IOBluetoothDeviceNotification = None

AUDIO_KEYWORDS = [
    'buds', 'headphones', 'headset', 'earphones', 'earbuds', 'audio',
    'speaker', 'sound', 'enco', 'bullets', 'airpods', 'tws', 'wireless stereo'
]
NON_AUDIO_KEYWORDS = [
    'mouse', 'keyboard', 'trackpad', 'keypad', 'remote', 'pencil',
    'iphone', 'ipad', 'macbook', 'imac', 'watch'
]


def log(msg: str):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] [BluetoothMonitor] {msg}', flush=True)


def is_bluetooth_audio_device(device) -> bool:
    """
    Determines whether a Bluetooth device is an audio output/input device.
    Uses native macOS IOBluetooth Class of Device (CoD), SDP services, and audio heuristics.
    """
    if not device:
        return False

    name = ''
    try:
        name = (device.getName() or device.nameOrAddress() or '').lower()
    except Exception:
        pass

    # 1. Negative rejection: Ignore known non-audio device keywords
    if any(k in name for k in NON_AUDIO_KEYWORDS):
        return False

    # 2. Native Bluetooth Class of Device (CoD)
    try:
        cod = device.classOfDevice() if hasattr(device, 'classOfDevice') else 0
        if cod != 0:
            major_dev = (cod >> 8) & 0x1F
            has_audio_svc = bool(cod & 0x200000)   # Bit 21: Audio service
            has_rendering = bool(cod & 0x040000)   # Bit 18: Rendering (Speaker/Headphones)
            has_capturing = bool(cod & 0x080000)   # Bit 19: Capturing (Microphone)

            # Major Device Class 0x04 = Audio/Video
            if major_dev == 0x04 or has_audio_svc or (has_rendering and has_capturing):
                return True

            # Non-audio major classes: 0x01 = Computer, 0x02 = Phone, 0x05 = Peripheral
            if major_dev in [0x01, 0x02, 0x05]:
                return False
    except Exception:
        pass

    # 3. Audio profile SDP records (A2DP / HFP / HSP / AVRCP)
    try:
        svcs = device.services() or []
        for s in svcs:
            s_name = str(s.getServiceName() or '').lower()
            if any(k in s_name for k in ['audio', 'headset', 'handsfree', 'a2dp', 'avrcp', 'sound']):
                return True
    except Exception:
        pass

    # 4. Audio name heuristics
    if any(k in name for k in AUDIO_KEYWORDS):
        return True

    return False


def send_ipc_message(payload: Dict[str, Any]) -> bool:
    """Sends a newline-delimited JSON command to the running OnePlus Buds app via IPC."""
    if not os.path.exists(IPC_SOCKET_PATH):
        return False
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.5)
        client.connect(IPC_SOCKET_PATH)
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = client.recv(1024)
            if not chunk:
                break
            buf += chunk
        client.close()
        return len(buf) > 0
    except Exception:
        return False


def is_app_running() -> bool:
    """Checks whether OnePlus Buds.app is running via NSWorkspace or active IPC socket."""
    if os.path.exists(IPC_SOCKET_PATH):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(IPC_SOCKET_PATH)
            s.close()
            return True
        except Exception:
            pass

    ws = AppKit.NSWorkspace.sharedWorkspace()
    running_apps = ws.runningApplications() or []
    for app in running_apps:
        bid = app.bundleIdentifier()
        if bid in [APP_BUNDLE_ID, FALLBACK_BUNDLE_ID]:
            return True
    return False


class BluetoothEventObserver(AppKit.NSObject):
    """Objective-C notification observer for IOBluetooth events."""
    def initWithMonitor_(self, monitor):
        self = objc.super(BluetoothEventObserver, self).init()
        if not self:
            return None
        self.monitor = monitor
        return self

    def deviceConnected_device_(self, notification, device):
        if self.monitor:
            self.monitor.on_raw_device_connected(device)

    def deviceDisconnected_device_(self, notification, device):
        if self.monitor:
            self.monitor.on_raw_device_disconnected(device)

    def delayedCheckDevice_(self, device):
        if self.monitor:
            self.monitor.process_delayed_resolution(device)


class BluetoothAudioMonitor:
    """
    Thread-safe Bluetooth audio monitor.
    Enforces the single replacement specification:
      - Filters non-audio and unsupported devices
      - Retries SDP name resolution up to 3 times
      - Deduplicates connection triggers using handled_devices
      - Routes triggers to running app via IPC or launches app
      - Handles disconnects cleanly
    """
    def __init__(
        self,
        on_connected: Optional[Callable[[Any, DeviceProfile, bool], None]] = None,
        on_disconnected: Optional[Callable[[Any, DeviceProfile], None]] = None,
        auto_invoke_app: bool = True
    ):
        self.on_connected_cb = on_connected
        self.on_disconnected_cb = on_disconnected
        self.auto_invoke_app = auto_invoke_app

        self.observer: Optional[BluetoothEventObserver] = None
        self.connect_notif_token = None
        self.disconnect_tokens: Dict[str, Any] = {}

        # Dictionary keyed by Bluetooth address to prevent repeated triggering
        self.handled_devices: Dict[str, Dict[str, Any]] = {}
        self.sdp_retries: Dict[str, int] = {}

        self.is_running = False
        self._lock = threading.Lock()

    def start(self):
        if self.is_running or not IOBluetoothDevice:
            return

        self.observer = BluetoothEventObserver.alloc().initWithMonitor_(self)

        # Register for global connection notifications
        try:
            self.connect_notif_token = IOBluetoothDevice.registerForConnectNotifications_selector_(
                self.observer, 'deviceConnected:device:'
            )
            log('Registered for native IOBluetooth connection notifications.')
        except Exception as e:
            log(f'Failed to register connect notification: {e}')

        # Register disconnect notifications on all paired devices
        self._register_disconnect_for_paired_devices()

        # Startup inspection: evaluate currently connected devices
        self.check_initial_connections()

        self.is_running = True

    def stop(self):
        if not self.is_running:
            return

        if self.connect_notif_token:
            try:
                self.connect_notif_token.unregister()
            except Exception:
                pass
            self.connect_notif_token = None

        for addr, tok in list(self.disconnect_tokens.items()):
            try:
                tok.unregister()
            except Exception:
                pass
        self.disconnect_tokens.clear()

        self.observer = None
        self.is_running = False
        log('Stopped.')

    def _safe_name(self, device) -> str:
        if not device:
            return ''
        try:
            return str(device.getName() or device.nameOrAddress() or '').strip()
        except Exception:
            return ''

    def _safe_address(self, device) -> str:
        if not device:
            return ''
        try:
            return str(device.getAddressString() or '').lower()
        except Exception:
            return ''

    def _register_disconnect_for_paired_devices(self):
        if not IOBluetoothDevice or not self.observer:
            return
        try:
            paired = IOBluetoothDevice.pairedDevices() or []
            for dev in paired:
                self._register_device_disconnect(dev)
        except Exception as e:
            log(f'Error registering paired devices: {e}')

    def _register_device_disconnect(self, device):
        if not device or not self.observer:
            return
        addr = self._safe_address(device)
        if not addr or addr in self.disconnect_tokens:
            return
        try:
            tok = device.registerForDisconnectNotification_selector_(
                self.observer, 'deviceDisconnected:device:'
            )
            if tok:
                self.disconnect_tokens[addr] = tok
        except Exception:
            pass

    def check_initial_connections(self):
        """Startup behavior: evaluate currently connected devices."""
        if not IOBluetoothDevice:
            return

        connected_found = False
        try:
            paired = IOBluetoothDevice.pairedDevices() or []
            for dev in paired:
                try:
                    if dev.isConnected() and is_bluetooth_audio_device(dev):
                        self._process_device_connected(dev, is_initial=True)
                        connected_found = True
                except Exception:
                    pass
        except Exception as e:
            log(f'Error during startup device check: {e}')

        if not connected_found:
            log('No supported Bluetooth audio devices connected at startup. Remaining idle.')

    def on_raw_device_connected(self, device):
        self._register_device_disconnect(device)
        self._process_device_connected(device, is_initial=False)

    def on_raw_device_disconnected(self, device):
        addr = self._safe_address(device)
        name = self._safe_name(device)
        if not addr:
            return

        with self._lock:
            was_handled = addr in self.handled_devices
            info = self.handled_devices.pop(addr, None)
            if addr in self.sdp_retries:
                del self.sdp_retries[addr]

        if was_handled:
            dev_name = info.get('name', name) if info else name
            log(f'Supported audio device disconnected: {dev_name}')

            # Notify running app via IPC
            sent = send_ipc_message({
                'command': 'device_disconnected',
                'device_name': dev_name,
                'device_address': addr
            })
            if sent:
                log('Notified running OnePlus Buds app of disconnect via IPC.')

            if self.on_disconnected_cb:
                prof = info.get('profile') if info else None
                try:
                    self.on_disconnected_cb(device, prof)
                except Exception as e:
                    log(f'Error in on_disconnected callback: {e}')

    def process_delayed_resolution(self, device):
        """Callback for scheduled SDP name resolution retries."""
        self._process_device_connected(device, is_initial=False)

    def _process_device_connected(self, device, is_initial: bool = False):
        addr = self._safe_address(device)
        if not addr:
            return

        # 1. Device must be connected right now
        try:
            if hasattr(device, 'isConnected') and not device.isConnected():
                return
        except Exception:
            pass

        name = self._safe_name(device)

        # 2. SDP Name Resolution Check
        raw_mac = addr.replace(':', '-').lower()
        is_name_unresolved = (not name) or (name.lower().replace(':', '-') == raw_mac)

        profile = match_supported_device(name) or get_device_profile(name)

        if not profile and is_name_unresolved:
            with self._lock:
                retries = self.sdp_retries.get(addr, 0)
                if retries < 3:
                    self.sdp_retries[addr] = retries + 1
                    log(f'Device name pending SDP resolution for {addr}. Scheduling retry {retries + 1}/3 in 0.5s...')
                    if self.observer:
                        self.observer.performSelector_withObject_afterDelay_('delayedCheckDevice:', device, 0.5)
                    return
                else:
                    log(f'SDP resolution timed out for device {addr}.')

        # 3. Filter: Must be a Bluetooth audio device
        if not is_bluetooth_audio_device(device):
            return

        # 4. Filter: Must exist in device_manager supported catalog
        if not profile:
            log(f"Connected audio device '{name}' is not in supported catalog. Taking no action.")
            return

        # 5. Prevent repeated triggering using handled_devices
        with self._lock:
            if addr in self.handled_devices:
                return
            self.handled_devices[addr] = {
                'name': profile.name,
                'profile': profile,
                'timestamp': time.time()
            }
            if addr in self.sdp_retries:
                del self.sdp_retries[addr]

        log(f'Supported audio device connected: {profile.name} (Model: {profile.model_code}, Address: {addr})')

        # Callback if registered
        if self.on_connected_cb:
            try:
                self.on_connected_cb(device, profile, is_initial)
            except Exception as e:
                log(f'Error in on_connected callback: {e}')

        # 6. Companion app handoff (only when auto_invoke_app=True)
        if self.auto_invoke_app:
            self._handoff_to_app(profile.name, addr, is_initial)

    def _handoff_to_app(self, device_name: str, device_address: str, is_initial: bool):
        """Routes connection trigger to app via IPC or launches the app."""
        ipc_payload = {
            'command': 'device_connected',
            'device_name': device_name,
            'device_address': device_address
        }
        if send_ipc_message(ipc_payload):
            log('Notified running OnePlus Buds app via IPC.')
            return

        if is_app_running():
            time.sleep(0.5)
            if send_ipc_message(ipc_payload):
                log('Notified running OnePlus Buds app via IPC.')
                return

        log('Launching OnePlus Buds app.')
        if os.path.isdir(APP_PATH):
            try:
                ws = AppKit.NSWorkspace.sharedWorkspace()
                app_url = Foundation.NSURL.fileURLWithPath_(APP_PATH)
                options = AppKit.NSWorkspaceLaunchDefault
                if is_initial:
                    options = AppKit.NSWorkspaceLaunchWithoutActivation
                ws.launchApplicationAtURL_options_configuration_error_(
                    app_url,
                    options,
                    {},
                    None
                )
            except Exception as e:
                log(f'NSWorkspace launch error: {e}. Falling back to open.')
                subprocess.Popen(['/usr/bin/open', '-a', APP_PATH])
        else:
            log(f'Error: {APP_PATH} does not exist on disk!')


def main():
    log('Initializing OnePlus Buds Bluetooth Audio Connection Watcher...')
    monitor = BluetoothAudioMonitor(auto_invoke_app=True)
    monitor.start()

    run_loop = Foundation.NSRunLoop.currentRunLoop()
    while True:
        run_loop.runMode_beforeDate_(Foundation.NSDefaultRunLoopMode, Foundation.NSDate.dateWithTimeIntervalSinceNow_(1.0))


if __name__ == '__main__':
    main()
