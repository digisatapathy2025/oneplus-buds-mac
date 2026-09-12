#!/usr/bin/env python3
"""
buds_controller.py
CLI controller for OnePlus Buds macOS Companion App.
Queries and controls the live OnePlus Buds app via UNIX domain socket IPC.
"""

import os
import sys
import json
import socket
import argparse
from typing import Optional, Dict, Any

IPC_SOCKET_PATH = '/tmp/oneplus_buds_ipc.sock'


def send_ipc_command(payload: Dict[str, Any], timeout: float = 3.0) -> Dict[str, Any]:
    """Sends a newline-delimited JSON request to the active IPC server and returns response."""
    if not os.path.exists(IPC_SOCKET_PATH):
        raise ConnectionRefusedError('IPC socket does not exist')

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(IPC_SOCKET_PATH)
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))

        buf = ""
        while True:
            while "\n" not in buf:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8")
            if "\n" not in buf:
                break
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if "event" in parsed and "status" not in parsed:
                continue
            return parsed
        return {"status": "error", "message": "Empty response from IPC server"}
    finally:
        try:
            client.close()
        except Exception:
            pass


def print_status(resp: Dict[str, Any], raw_json: bool = False):
    if raw_json:
        print(json.dumps(resp, indent=2))
        return

    if resp.get('status') != 'ok':
        print(f"❌ Server returned error: {resp.get('message', 'Unknown error')}")
        return

    app_status = resp.get('app_status', 'unknown').capitalize()
    dev_name = resp.get('device_name') or 'None'
    dev_addr = resp.get('device_address') or 'N/A'
    model = resp.get('model') or 'N/A'
    noise_mode = resp.get('noise_mode', 'unknown')
    battery = resp.get('battery', {}) or {}

    b_left = f"{battery.get('left')}%" if battery.get('left') is not None else '--'
    b_right = f"{battery.get('right')}%" if battery.get('right') is not None else '--'
    b_case = f"{battery.get('case')}%" if battery.get('case') is not None else '--'

    print('┌────────────────────────────────────────────────────────┐')
    print('│              OnePlus Buds macOS Status                 │')
    print('├────────────────────────────────────────────────────────┤')
    print(f'│  App State    : {app_status:<39}│')
    print(f'│  Device Name  : {dev_name:<39}│')
    print(f'│  Model / Code : {model:<39}│')
    print(f'│  Address      : {dev_addr:<39}│')
    print('├────────────────────────────────────────────────────────┤')
    print(f'│  🔋 Left Earbud : {b_left:<10} Right Earbud : {b_right:<10} │')
    print(f'│     Case        : {b_case:<37}│')
    print('├────────────────────────────────────────────────────────┤')
    print(f'│  🎧 Noise Mode : {noise_mode:<39}│')
    print('└────────────────────────────────────────────────────────┘')


def main():
    parser = argparse.ArgumentParser(
        description='CLI controller for OnePlus Buds macOS Companion App (IPC client)',
        prog='buds_controller.py'
    )
    subparsers = parser.add_subparsers(dest='command', help='Subcommand to execute')

    # status
    p_status = subparsers.add_parser('status', help='Query current app status and device state')
    p_status.add_argument('--json', action='store_true', help='Print status in raw JSON')

    # anc
    p_anc = subparsers.add_parser('anc', help='Set Active Noise Control (ANC) mode')
    p_anc.add_argument('mode', choices=['off', 'transparency', 'anc', '0', '1', '2'], help='Mode: off (0), transparency (1), anc (2)')

    # connect
    p_conn = subparsers.add_parser('connect', help='Send device_connected IPC event')
    p_conn.add_argument('device_name', help='Device name (e.g. "OnePlus Buds 3")')
    p_conn.add_argument('device_address', nargs='?', default='', help='Bluetooth device address (optional)')

    # disconnect
    p_disc = subparsers.add_parser('disconnect', help='Send device_disconnected IPC event')
    p_disc.add_argument('device_name', help='Device name')
    p_disc.add_argument('device_address', nargs='?', default='', help='Bluetooth device address (optional)')

    # ping
    subparsers.add_parser('ping', help='Ping the running app IPC server')

    # If run with no arguments, default to status
    if len(sys.argv) == 1:
        args = parser.parse_args(['status'])
    else:
        args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == 'status':
            resp = send_ipc_command({'command': 'status'})
            print_status(resp, raw_json=args.json)

        elif args.command == 'anc':
            mode_map = {'off': 0, '0': 0, 'transparency': 1, '1': 1, 'anc': 2, '2': 2}
            int_mode = mode_map[args.mode.lower()]
            resp = send_ipc_command({'command': 'set_anc', 'mode': int_mode})
            if resp.get('status') == 'ok':
                print(f'✅ ANC mode successfully set to {args.mode} (mode {int_mode}).')
            else:
                print(f"❌ Failed to set ANC: {resp.get('message', 'Unknown error')}")
                sys.exit(1)

        elif args.command == 'connect':
            resp = send_ipc_command({
                'command': 'device_connected',
                'device_name': args.device_name,
                'device_address': args.device_address
            })
            if resp.get('status') == 'ok':
                print(f"✅ Sent device_connected event for '{args.device_name}'.")
            else:
                print(f"❌ Error: {resp.get('message')}")
                sys.exit(1)

        elif args.command == 'disconnect':
            resp = send_ipc_command({
                'command': 'device_disconnected',
                'device_name': args.device_name,
                'device_address': args.device_address
            })
            if resp.get('status') == 'ok':
                print(f"✅ Sent device_disconnected event for '{args.device_name}'.")
            else:
                print(f"❌ Error: {resp.get('message')}")
                sys.exit(1)

        elif args.command == 'ping':
            resp = send_ipc_command({'command': 'ping'})
            print(f'Response: {resp}')

    except (ConnectionRefusedError, FileNotFoundError, socket.error):
        print(f'❌ OnePlus Buds app is not currently running or IPC socket ({IPC_SOCKET_PATH}) is unavailable.', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'❌ Error communicating with OnePlus Buds app: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
