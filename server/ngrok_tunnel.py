"""
Ngrok Tunnel Manager for POS Billing Server

Provides functionality to start/stops ngrok tunnels, manage .env updates,
and handle tunnel lifecycle in pure Python (no asyncio required).

Usage:
    from server.ngrok_tunnel import NgrokTunnelManager

    # Start tunnel with auth token
    manager = NgrokTunnelManager(port=8001, auth_token="3L0Mmv0oNFh1tRaQ7rqXbHn0Kzr_349U7n7GppfaaDb23Moam")
    manager.start()

    # Stop tunnel
    manager.stop()

    # Or run as script: python -m server.ngrok_tunnel start|stop --auth-token TOKEN
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
SERVER_ENV_FILE = REPO_ROOT / "server" / ".env"
ENV_BACKUP = REPO_ROOT / ".env.ngrok-backup"
SERVER_ENV_BACKUP = REPO_ROOT / "server" / ".env.ngrok-backup"
NGROK_EXE = shutil.which("ngrok") or shutil.find_executable("ngrok")

# Ngrok local API
NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels"


class NgrokTunnelManager:
    """Manages ngrok tunnel lifecycle for the POS billing server."""

    def __init__(
        self,
        port: int = 8001,
        auth_token: Optional[str] = None,
        ngrok_path: Optional[str] = None,
    ):
        self.port = port
        self.local_url = "http://127.0.0.1:" + str(port)
        self.ngrok_exe = ngrok_path or NGROK_EXE
        self.auth_token = auth_token
        self.ngrok_process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None
        self.webhook_url: Optional[str] = None

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _get_tunnels() -> Optional[list[dict]]:
        """Fetch tunnels from ngrok local API (synchronous)."""
        try:
            req = urllib.request.Request(NGROK_API_URL)
            with urllib.request.urlopen(req, timeout=5) as response:
                body = response.read()
                return json.loads(body)
        except Exception:
            return None

    @staticmethod
    def _find_tunnel_by_port(tunnels: list[dict], port: int) -> Optional[dict]:
        """Find tunnel matching the given port."""
        for tunnel in tunnels:
            config = tunnel.get("config", {}) or {}
            addr = config.get("addr", "") or ""
            if f":{port}" in addr or str(port) in addr:
                return tunnel
        return None

    # ------------------------------------------------------------------ start

    def ensure_auth_token(self) -> bool:
        """Ensure ngrok has an auth token. Uses --authtoken flag if set."""
        if self.auth_token:
            print("Auth token provided via parameter - will use --authtoken flag")
            return True
        # Fall back to reading from ngrok.yml (may be corrupted)
        # If that fails, the user must set NGrok auth token manually
        token = None
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:2468/config")
            # ngrok may not have a config endpoint, so we skip this
            pass
        except Exception:
            pass
        if not self.auth_token:
            print(
                "Ngrok auth token not configured. "
                "Set auth_token parameter or use: ngrok config add-authtoken <TOKEN>"
            )
            return False
        return True

    def start(self, timeout: int = 60) -> bool:
        """Start ngrok tunnel. Returns True if successful."""
        # Ensure auth token setup
        if not self.ensure_auth_token():
            return False

        # Kill any existing ngrok we started (from previous run)
        self._kill_existing_ngrok()

        # Build ngrok args
        args = [self.ngrok_exe, "http"]
        if self.auth_token:
            args.append("--authtoken")
            args.append(self.auth_token)
        args.append("127.0.0.1:" + str(self.port))

        # Prepare log files
        log_dir = REPO_ROOT
        log_files = [
            log_dir / "ngrok.log",
            log_dir / "ngrok.stdout.log",
            log_dir / "ngrok.stderr.log",
        ]
        for lf in log_files:
            try:
                if lf.is_file():
                    lf.unlink()
            except Exception:
                pass

        try:
            self.ngrok_process = subprocess.Popen(
                args,
                cwd=str(REPO_ROOT),
                stdout=open(str(log_dir / "ngrok.stdout.log"), "w"),
                stderr=open(str(log_dir / "ngrok.stderr.log"), "w"),
            )
        except Exception as e:
            print("Failed to start ngrok: " + str(e))
            return False

        # Wait for tunnel to be available
        deadline = time.time() + timeout
        while time.time() < deadline:
            tunnels = NgrokTunnelManager._get_tunnels()
            if tunnels:
                tunnel = NgrokTunnelManager._find_tunnel_by_port(tunnels, self.port)
                if tunnel:
                    self.public_url = NgrokTunnelManager._parse_tunnel_data(
                        tunnel.get("uri", "")
                    )
                    self.webhook_url = (
                        self.public_url.rstrip("/") + "/webhooks/payment/midtrans"
                    )
                    print("Ngrok tunnel aktif: " + self.public_url)
                    print("Webhook URL: " + self.webhook_url)
                    self._update_env_files()
                    return True
            time.sleep(1)

        print("Tunnel tidak naik dalam " + str(timeout) + " detik.")
        self._show_logs()
        self.stop()
        return False

    # ------------------------------------------------------------------ stop

    def stop(self) -> bool:
        """Stop ngrok tunnel and restore .env files."""
        if self.ngrok_process:
            try:
                self.ngrok_process.terminate()
                try:
                    self.ngrok_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.ngrok_process.kill()
                print("Ngrok process dihentikan")
            except Exception as e:
                print("Error stopping ngrok process: " + str(e))
            self.ngrok_process = None

        # Restore .env files
        restored = True
        if ENV_BACKUP.is_file():
            try:
                shutil.copy2(str(ENV_BACKUP), str(ENV_FILE))
                print(".env root dikembalikan dari cadangan")
            except Exception as e:
                print("Gagal restore .env root: " + str(e))
                restored = False
        else:
            self._restore_server_env()

        if SERVER_ENV_BACKUP.is_file():
            try:
                shutil.copy2(str(SERVER_ENV_BACKUP), str(SERVER_ENV_FILE))
                print("server/.env dikembalikan dari cadangan")
            except Exception as e:
                print("Gagal restore server/.env: " + str(e))
                restored = False
        else:
            self._restore_server_env()

        self.public_url = None
        self.webhook_url = None

        print("Semua tunnel dihentikan dan .env dikembalikan.")
        return restored

    def _kill_existing_ngrok(self) -> None:
        """Kill any existing ngrok processes."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ngrok.exe"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.splitlines():
                if "ngrok" in line.lower():
                    pid = int(line.split()[1])
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"], capture_output=True
                    )
                    print("Killed existing ngrok PID " + str(pid))
        except Exception as e:
            print("Error killing existing ngrok: " + str(e))

    def _is_port_listening(self, port: int) -> bool:
        """Check if a port has something listening."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False

    # ------------------------------------------------------------------ env management

    def _update_env_files(self) -> None:
        """Update .env files with the new public URL."""
        if not self.public_url:
            return

        # Root .env: billing_server_url
        self._update_root_env("billing_server_url", self.public_url)

        # server/.env: BASE_URL and MIDTRANS_NOTIFICATION_URL
        self._update_server_env(self.public_url, self.webhook_url)

    def _update_root_env(self, key: str, value: str) -> None:
        """Update a key in root .env, with backup."""
        # Backup
        if ENV_FILE.is_file():
            try:
                shutil.copy2(str(ENV_FILE), str(ENV_BACKUP))
                print("Cadangan .env -> .env.ngrok-backup")
            except Exception as e:
                print("Gagal buat cadangan .env: " + str(e))

        # Set value
        lines = []
        if ENV_FILE.is_file():
            lines = [l for l in open(ENV_FILE, "r", encoding="utf-8")]
        new_lines = []
        found = False
        for line in lines:
            k = line.split("=", 1)[0].strip()
            if k == key:
                new_lines.append(key + "=" + value + "\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(key + "=" + value + "\n")
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(key + " = " + value)

    def _update_server_env(self, base_url: str, webhook_url: str) -> None:
        """Update server/.env with BASE_URL and MIDTRANS_NOTIFICATION_URL."""
        # Backup
        if SERVER_ENV_FILE.is_file():
            try:
                shutil.copy2(str(SERVER_ENV_FILE), str(SERVER_ENV_BACKUP))
                print("Cadangan server/.env -> server/.env.ngrok-backup")
            except Exception as e:
                print("Gagal buat cadangan server/.env: " + str(e))

        # Update BASE_URL
        self._set_server_key("BASE_URL", base_url)

        # Update MIDTRANS_NOTIFICATION_URL
        self._set_server_key("MIDTRANS_NOTIFICATION_URL", webhook_url)

    def _set_server_key(self, key: str, value: str) -> None:
        """Set a key in server/.env with backup logic."""
        lines = []
        if SERVER_ENV_FILE.is_file():
            lines = [l for l in open(SERVER_ENV_FILE, "r", encoding="utf-8")]
        new_lines = []
        found_key = False
        for line in lines:
            k = line.split("=", 1)[0].strip()
            if k == key:
                new_lines.append(key + "=" + value + "\n")
                found_key = True
            else:
                new_lines.append(line)
        if not found_key:
            new_lines.append(key + "=" + value + "\n")
        with open(SERVER_ENV_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(server + "/.env " + key + " = " + value)

    def _restore_server_env(self) -> None:
        """Restore server/.env to local values (no ngrok)."""
        local_url = "http://127.0.0.1:" + str(self.port)
        self._set_server_key("BASE_URL", local_url)
        self._set_server_key("MIDTRANS_NOTIFICATION_URL", "")

    # ------------------------------------------------------------------ logging

    def _show_logs(self) -> None:
        """Show ngrok logs for debugging."""
        log_file = REPO_ROOT / "ngrok.log"
        if log_file.is_file():
            print("\n--- ngrok.log ---")
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for line in lines[-20:]:
                    print(line.rstrip())

    # ------------------------------------------------------------------ CLI

    @classmethod
    def run_cli(cls, args: list[str]) -> int:
        """Run as CLI: python -m server.ngrok_tunnel start|stop [--auth-token TOKEN] [port]"""
        port = 8001
        auth_token = None

        # Parse arguments
        i = 0
        while i < len(args):
            if args[i] == "--auth-token" and i + 1 < len(args):
                auth_token = args[i + 1]
                i += 2
            elif args[i].isdigit() and len(args) > i + 1:
                # Could be port followed by something, or just port
                try:
                    port = int(args[i])
                    i += 1
                except ValueError:
                    i += 1
            else:
                i += 1

        manager = cls(port=port, auth_token=auth_token)

        if len(args) == 0:
            print("Usage: python -m server.ngrok_tunnel start|stop [--auth-token TOKEN] [port]")
            return 1

        command = args[0].lower() if args else "start"

        if command == "start":
            return 0 if manager.start() else 1
        elif command == "stop":
            manager.stop()
            return 0
        else:
            print("Unknown command: " + command)
            print("Usage: python -m server.ngrok_tunnel start|stop [--auth-token TOKEN] [port]")
            return 1


def main():
    """Entry point when run as script."""
    import sys

    result = NgrokTunnelManager.run_cli(sys.argv[1:])
    sys.exit(result)


if __name__ == "__main__":
    main()