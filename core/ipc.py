#!/usr/bin/env python3
"""
Local Unix Domain Socket IPC for OnePlus Buds Companion App.
Enables GUI and CLI to attach to the live CoreBluetooth menu bar session seamlessly.
"""

import os
import sys
import json
import time
import socket
import select
import threading
from typing import Optional, Dict, Any, Callable, List

IPC_SOCKET_PATH = "/tmp/oneplus_buds_ipc.sock"


class BudsIPCServer:
    """
    Lightweight Unix domain socket server hosted by the menu bar companion app.
    Dispatches incoming control commands directly to the active BaseBudsController.
    """
    def __init__(self, controller):
        self.controller = controller
        self.server_sock: Optional[socket.socket] = None
        self.clients: List[socket.socket] = []
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        if self.is_running:
            return

        # Clean up stale socket if left behind
        if os.path.exists(IPC_SOCKET_PATH):
            try:
                # Test if another server is actively listening
                test_s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test_s.connect(IPC_SOCKET_PATH)
                test_s.close()
                print("[IPCServer] Active server already running on socket.", file=sys.stderr)
                return
            except (socket.error, ConnectionRefusedError):
                try:
                    os.unlink(IPC_SOCKET_PATH)
                except OSError:
                    pass

        try:
            self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_sock.bind(IPC_SOCKET_PATH)
            self.server_sock.listen(5)
            self.is_running = True
            self.thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.thread.start()
            print(f"[IPCServer] Listening on {IPC_SOCKET_PATH}")
        except Exception as e:
            print(f"[IPCServer] Failed to start socket server: {e}", file=sys.stderr)

    def stop(self):
        self.is_running = False
        with self._lock:
            for c in self.clients:
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None

        if os.path.exists(IPC_SOCKET_PATH):
            try:
                os.unlink(IPC_SOCKET_PATH)
            except OSError:
                pass

    def broadcast_state(self, exclude: Optional[socket.socket] = None):
        """Sends current state update to all attached subscribers (e.g. GUI)."""
        if not self.is_running:
            return
        payload = json.dumps({"event": "state_update", "state": self.controller.state.to_dict()}) + "\n"
        data = payload.encode("utf-8")

        with self._lock:
            disconnected = []
            for c in self.clients:
                if c == exclude:
                    continue
                try:
                    c.sendall(data)
                except Exception:
                    disconnected.append(c)
            for d in disconnected:
                if d in self.clients:
                    self.clients.remove(d)

    def _listen_loop(self):
        while self.is_running and self.server_sock:
            try:
                r_list, _, _ = select.select([self.server_sock], [], [], 1.0)
                if not r_list:
                    continue
                client, _ = self.server_sock.accept()
                with self._lock:
                    self.clients.append(client)
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, client: socket.socket):
        buf = ""
        while self.is_running:
            try:
                data = client.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line)
                        resp = self._process_request(req, client=client)
                        client.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    except json.JSONDecodeError:
                        err = {"status": "error", "message": "Invalid JSON"}
                        client.sendall((json.dumps(err) + "\n").encode("utf-8"))
            except Exception:
                break

        with self._lock:
            if client in self.clients:
                self.clients.remove(client)
        try:
            client.close()
        except Exception:
            pass

    def _build_status_response(self) -> Dict[str, Any]:
        ctrl = self.controller
        state = getattr(ctrl, "state", None)

        is_connected = getattr(ctrl, "is_connected", False)
        is_connecting = getattr(ctrl, "is_connecting", False) or getattr(ctrl, "is_scanning", False)
        status_msg = getattr(ctrl, "status_message", "") or (state.status_message if state else "")

        if is_connected:
            app_status = "connected"
        elif is_connecting:
            app_status = "connecting"
        elif status_msg.lower() == "disconnected":
            app_status = "disconnected"
        elif getattr(ctrl, "device_name", None) or (state and getattr(state, "device_name", None)):
            app_status = "disconnected"
        else:
            app_status = "idle"

        dev_name = getattr(ctrl, "device_name", "") or (state.device_name if state else "") or ""
        dev_addr = getattr(ctrl, "address", "") or (state.address if state else "") or ""

        prof = getattr(ctrl, "profile", None) or (state.profile if state else None)
        model = ""
        if prof:
            model = getattr(prof, "model_code", "") or getattr(prof, "name", "")
        elif state and getattr(state, "product_id", ""):
            model = state.product_id

        # Battery extraction
        battery_data = {"left": None, "right": None, "case": None}
        raw_bat = getattr(ctrl, "battery", {}) or (state.battery if state else {})
        if isinstance(raw_bat, dict):
            # Left
            left_info = raw_bat.get("left")
            if isinstance(left_info, dict) and left_info.get("connected"):
                battery_data["left"] = left_info.get("level")
            elif isinstance(left_info, int):
                battery_data["left"] = left_info

            # Right
            right_info = raw_bat.get("right")
            if isinstance(right_info, dict) and right_info.get("connected"):
                battery_data["right"] = right_info.get("level")
            elif isinstance(right_info, int):
                battery_data["right"] = right_info

            # Case
            case_info = raw_bat.get("case")
            if isinstance(case_info, dict) and case_info.get("connected"):
                battery_data["case"] = case_info.get("level")
            elif isinstance(case_info, int):
                battery_data["case"] = case_info

            # Neckband single
            single_info = raw_bat.get("single")
            if isinstance(single_info, dict) and single_info.get("connected"):
                if battery_data["left"] is None and battery_data["right"] is None:
                    battery_data["left"] = single_info.get("level")
                    battery_data["right"] = single_info.get("level")

        # Noise mode extraction: off | transparency | anc | unknown
        cur_noise = getattr(ctrl, "current_noise_mode", "") or (state.current_noise_mode if state else "")
        last_primary = getattr(ctrl, "last_primary_mode", "") or (state.last_primary_mode if state else "")

        check_val = (cur_noise or last_primary or "").strip().lower()
        if check_val in ["off"]:
            noise_mode = "off"
        elif check_val in ["transparency"]:
            noise_mode = "transparency"
        elif check_val in ["noise cancellation", "anc", "high", "moderate", "low", "auto", "mild", "depth", "smart"]:
            noise_mode = "anc"
        else:
            noise_mode = "unknown"

        return {
            "status": "ok",
            "app_status": app_status,
            "device_name": dev_name,
            "device_address": dev_addr,
            "model": model,
            "battery": battery_data,
            "noise_mode": noise_mode
        }

    def _process_request(self, req: Dict[str, Any], client: Optional[socket.socket] = None) -> Dict[str, Any]:
        cmd = req.get("command")

        # 1. Canonical Status
        if cmd == "status":
            return self._build_status_response()

        # 2. Canonical Device Connected
        elif cmd == "device_connected":
            dev_name = req.get("device_name", "")
            dev_addr = req.get("device_address", "")
            from device_manager import match_supported_device, get_device_profile
            prof = match_supported_device(dev_name) or get_device_profile(dev_name)
            if hasattr(self.controller, "delegate") and self.controller.delegate:
                app = self.controller.delegate
                if hasattr(app, "on_bluetooth_device_connected"):
                    app.on_bluetooth_device_connected(None, prof, is_initial=False)
            elif hasattr(self.controller, "attempt_fast_connect"):
                if prof and hasattr(self.controller, "state"):
                    if self.controller.state.device_name != prof.name:
                        self.controller.state.address = ""
                    if hasattr(self.controller, "_handshake_started"):
                        self.controller._handshake_started = False
                    if hasattr(self.controller, "cancel_connection_timeout"):
                        self.controller.cancel_connection_timeout()
                    self.controller.state.profile = prof
                    self.controller.state.device_name = prof.name
                self.controller.attempt_fast_connect()
            return {"status": "ok"}

        # 3. Canonical Device Disconnected
        elif cmd == "device_disconnected":
            dev_name = req.get("device_name", "")
            from device_manager import match_supported_device, get_device_profile
            prof = match_supported_device(dev_name) or get_device_profile(dev_name)
            if hasattr(self.controller, "delegate") and self.controller.delegate:
                app = self.controller.delegate
                if hasattr(app, "on_bluetooth_device_disconnected"):
                    app.on_bluetooth_device_disconnected(None, prof)
            else:
                if hasattr(self.controller, "cancel_connection_timeout"):
                    self.controller.cancel_connection_timeout()
                if hasattr(self.controller, "peripheral") and self.controller.peripheral:
                    try:
                        self.controller.central.cancelPeripheralConnection_(self.controller.peripheral)
                    except Exception:
                        pass
                    self.controller.peripheral = None
                self.controller.is_connected = False
                self.controller.is_connecting = False
                if hasattr(self.controller, "_handshake_started"):
                    self.controller._handshake_started = False
                if hasattr(self.controller, "state"):
                    self.controller.state.address = ""
                if hasattr(self.controller, "status_message"):
                    self.controller.status_message = "Disconnected"
            return {"status": "ok"}

        # 4. Canonical Set ANC (0=Off, 1=Transparency, 2=ANC)
        elif cmd == "set_anc":
            mode = req.get("mode")
            if mode == 0:
                target_mode = "Off"
            elif mode == 1:
                target_mode = "Transparency"
            elif mode == 2:
                target_mode = "Noise Cancellation"
            else:
                return {"status": "error", "message": "Invalid mode: must be 0 (Off), 1 (Transparency), or 2 (ANC)"}

            if hasattr(self.controller, "set_primary_mode"):
                self.controller.set_primary_mode(target_mode)
            elif hasattr(self.controller, "set_noise_mode"):
                self.controller.set_noise_mode(target_mode)
            self.broadcast_state(exclude=client)
            return {"status": "ok"}

        # Backward compatibility / internal commands
        elif cmd == "ping":
            return {"status": "ok", "message": "pong"}

        elif cmd == "get_state":
            return {"status": "ok", "state": self.controller.state.to_dict()}

        elif cmd == "set_primary_mode":
            mode = req.get("mode", "")
            self.controller.set_primary_mode(mode)
            self.broadcast_state(exclude=client)
            return {"status": "ok", "state": self.controller.state.to_dict()}

        elif cmd == "set_noise_mode":
            mode = req.get("mode", "")
            self.controller.set_noise_mode(mode)
            self.broadcast_state(exclude=client)
            return {"status": "ok", "state": self.controller.state.to_dict()}

        elif cmd == "set_feature":
            fid = int(req.get("feature_id", 0))
            enable = bool(req.get("enable", False))
            self.controller.set_feature(fid, enable)
            self.broadcast_state(exclude=client)
            return {"status": "ok", "state": self.controller.state.to_dict()}

        elif cmd == "set_eq":
            preset = req.get("preset", "")
            self.controller.set_eq(preset)
            self.broadcast_state(exclude=client)
            return {"status": "ok", "state": self.controller.state.to_dict()}

        elif cmd == "refresh":
            self.controller.refresh()
            return {"status": "ok", "state": self.controller.state.to_dict()}

        return {"status": "error", "message": f"Unknown command: {cmd}"}


class BudsIPCClient:
    """
    Client interface used by GUI and CLI to communicate with a running menu bar agent.
    """
    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.subscriber_thread: Optional[threading.Thread] = None
        self.on_state_update: Optional[Callable[[Dict[str, Any]], None]] = None
        self.is_connected = False
        self.is_subscribing = False
        self._lock = threading.Lock()

    @staticmethod
    def is_server_active() -> bool:
        if not os.path.exists(IPC_SOCKET_PATH):
            return False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(IPC_SOCKET_PATH)
            s.sendall(b'{"command": "ping"}\n')
            data = s.recv(1024)
            s.close()
            return b"pong" in data
        except Exception:
            return False

    def connect(self) -> bool:
        if not os.path.exists(IPC_SOCKET_PATH):
            return False
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(2.0)
            self.sock.connect(IPC_SOCKET_PATH)
            self.is_connected = True
            return True
        except Exception:
            self.sock = None
            self.is_connected = False
            return False

    def disconnect(self):
        self.is_connected = False
        self.is_subscribing = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        if getattr(self, "sub_sock", None):
            try:
                self.sub_sock.close()
            except Exception:
                pass
            self.sub_sock = None

    def send_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.sock:
                if not self.connect():
                    return None
            try:
                payload = json.dumps(req) + "\n"
                self.sock.sendall(payload.encode("utf-8"))
                # Read response
                buf = ""
                self.sock.settimeout(3.0)
                while "\n" not in buf:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8")
                line = buf.split("\n", 1)[0].strip()
                return json.loads(line) if line else None
            except Exception as e:
                self.disconnect()
                return None

    def query_status(self) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "status"})

    def set_anc_mode(self, mode: int) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "set_anc", "mode": mode})

    def notify_device_connected(self, name: str, address: str = "") -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "device_connected", "device_name": name, "device_address": address})

    def notify_device_disconnected(self, name: str, address: str = "") -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "device_disconnected", "device_name": name, "device_address": address})

    def get_state(self) -> Optional[Dict[str, Any]]:
        resp = self.send_request({"command": "get_state"})
        return resp.get("state") if resp and resp.get("status") == "ok" else None

    def set_primary_mode(self, mode: str) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "set_primary_mode", "mode": mode})

    def set_noise_mode(self, mode: str) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "set_noise_mode", "mode": mode})

    def set_feature(self, feature_id: int, enable: bool) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "set_feature", "feature_id": feature_id, "enable": enable})

    def set_eq(self, preset: str) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "set_eq", "preset": preset})

    def refresh(self) -> Optional[Dict[str, Any]]:
        return self.send_request({"command": "refresh"})

    def start_listening_updates(self, on_update: Callable[[Dict[str, Any]], None]):
        self.on_state_update = on_update
        try:
            self.sub_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sub_sock.connect(IPC_SOCKET_PATH)
            self.is_subscribing = True
            self.subscriber_thread = threading.Thread(target=self._sub_loop, daemon=True)
            self.subscriber_thread.start()
        except Exception as e:
            print(f"[IPCClient] Could not start update listener: {e}", file=sys.stderr)

    subscribe = start_listening_updates

    def _sub_loop(self):
        buf = ""
        while self.is_subscribing and self.sub_sock:
            try:
                self.sub_sock.settimeout(1.0)
                data = self.sub_sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if msg.get("event") == "state_update" and self.on_state_update:
                            self.on_state_update(msg.get("state", {}))
                    except json.JSONDecodeError:
                        pass
            except socket.timeout:
                continue
            except Exception:
                break
        if self.sub_sock:
            try:
                self.sub_sock.close()
            except Exception:
                pass
            self.sub_sock = None
