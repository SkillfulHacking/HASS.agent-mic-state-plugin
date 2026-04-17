"""
HASS.agent-mic-state-plugin
Connects to Discord via IPC named pipe to read voice channel state
for use as a HASS.Agent sensor.

Returns:
    stdout: JSON with voice_active, muted, deafened (all bool)
    exit code: 0 always (HASS.Agent expects clean exit)
"""

import struct
import json
import sys
import os
import logging
import urllib.request
import urllib.parse
import uuid
import win32file
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

CLIENT_ID = "1494532375496097853"
SCOPES    = ["rpc", "rpc.voice.read"]

# ── Opcodes ───────────────────────────────────────────────────────────────────

OP_HANDSHAKE = 0
OP_FRAME     = 1
OP_CLOSE     = 2

# ── Paths ─────────────────────────────────────────────────────────────────────

log_dir    = Path(os.environ.get("APPDATA", ".")) / "hass-mic-state"
log_dir.mkdir(parents=True, exist_ok=True)
log_file   = log_dir / "plugin.log"
token_file = log_dir / "token.json"

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=str(log_file),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ── Token cache ───────────────────────────────────────────────────────────────

import time

def load_token() -> str | None:
    try:
        data = json.loads(token_file.read_text())
        if not set(SCOPES).issubset(set(data.get("scopes", []))):
            log.info("Cached token missing required scopes, re-authorizing")
            return None
        if time.time() >= data.get("expires_at", 0):
            log.info("Cached token expired, attempting refresh")
            return _refresh_token(data.get("refresh_token"))
        return data.get("access_token")
    except Exception:
        return None


def save_token(access_token: str, refresh_token: str, expires_in: int, scopes: list) -> None:
    token_file.write_text(json.dumps({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "expires_at":    time.time() + expires_in - 60,  # 60s early margin
        "scopes":        scopes,
    }))


def clear_token() -> None:
    token_file.unlink(missing_ok=True)


def _refresh_token(refresh_token: str | None) -> str | None:
    if not refresh_token:
        clear_token()
        return None
    try:
        data = urllib.parse.urlencode({
            "client_id":     CLIENT_ID,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        }).encode()
        req = urllib.request.Request(
            "https://discord.com/api/oauth2/token",
            data=data,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        save_token(
            body["access_token"],
            body["refresh_token"],
            body.get("expires_in", 604800),
            body.get("scope", " ".join(SCOPES)).split(),
        )
        log.info("Token refreshed silently")
        return body["access_token"]
    except Exception as e:
        log.error(f"Token refresh failed: {e}")
        clear_token()
        return None

# ── OAuth2 token exchange (public client — no secret) ─────────────────────────

def exchange_code(code: str) -> tuple[str, str, int] | None:
    try:
        data = urllib.parse.urlencode({
            "client_id":  CLIENT_ID,
            "grant_type": "authorization_code",
            "code":       code,
        }).encode()
        req = urllib.request.Request(
            "https://discord.com/api/oauth2/token",
            data=data,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
        return body["access_token"], body["refresh_token"], body.get("expires_in", 604800)
    except Exception as e:
        log.error(f"Token exchange failed: {e}")
        return None

# ── Discord IPC (named pipe) ──────────────────────────────────────────────────

class DiscordIPC:
    def __init__(self):
        self.handle = None

    def connect(self) -> bool:
        for i in range(10):
            path = f"\\\\.\\pipe\\discord-ipc-{i}"
            try:
                self.handle = win32file.CreateFile(
                    path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None
                )
                log.debug(f"Connected to {path}")
                return True
            except Exception:
                continue
        return False

    def recv(self) -> tuple[int, dict]:
        _, header  = win32file.ReadFile(self.handle, 8)
        opcode, length = struct.unpack("<II", header)
        _, payload = win32file.ReadFile(self.handle, length)
        data = json.loads(payload)
        log.debug(f"IPC recv op={opcode} evt={data.get('evt')} cmd={data.get('cmd')}")
        return opcode, data

    def send(self, opcode: int, payload: dict) -> None:
        data  = json.dumps(payload).encode("utf-8")
        frame = struct.pack("<II", opcode, len(data)) + data
        win32file.WriteFile(self.handle, frame)
        log.debug(f"IPC send op={opcode} cmd={payload.get('cmd', 'HANDSHAKE')}")

    def send_recv(self, payload: dict) -> dict:
        self.send(OP_FRAME, payload)
        _, data = self.recv()
        return data

    def close(self) -> None:
        if self.handle:
            try:
                self.send(OP_CLOSE, {})
            except Exception:
                pass
            win32file.CloseHandle(self.handle)
            self.handle = None

# ── Core logic ────────────────────────────────────────────────────────────────

def check_discord_state() -> dict:
    result = {"voice_active": False, "muted": False, "deafened": False}

    ipc = DiscordIPC()
    if not ipc.connect():
        log.warning("Discord IPC pipe not found. Is Discord running?")
        return result

    try:
        ipc.send(OP_HANDSHAKE, {"v": 1, "client_id": CLIENT_ID})
        _, data = ipc.recv()
        log.debug(f"Handshake: evt={data.get('evt')}")

        access_token = load_token()
        resp = {}

        if access_token:
            resp = ipc.send_recv({
                "nonce": str(uuid.uuid4()),
                "cmd":   "AUTHENTICATE",
                "args":  {"access_token": access_token}
            })
            if resp.get("evt") == "ERROR":
                log.warning("Cached token rejected, re-authorizing")
                clear_token()
                access_token = None

        if not access_token:
            resp = ipc.send_recv({
                "nonce": str(uuid.uuid4()),
                "cmd":   "AUTHORIZE",
                "args":  {"client_id": CLIENT_ID, "scopes": SCOPES}
            })
            if resp.get("evt") == "ERROR":
                log.error(f"AUTHORIZE failed: {resp.get('data', {}).get('message')}")
                return result

            code = resp.get("data", {}).get("code")
            if not code:
                log.error("No auth code returned from AUTHORIZE")
                return result

            exchanged = exchange_code(code)
            if not exchanged:
                return result
            access_token, refresh_token, expires_in = exchanged

            resp = ipc.send_recv({
                "nonce": str(uuid.uuid4()),
                "cmd":   "AUTHENTICATE",
                "args":  {"access_token": access_token}
            })
            if resp.get("evt") == "ERROR":
                log.error(f"AUTHENTICATE failed: {resp.get('data', {}).get('message')}")
                clear_token()
                return result

            save_token(access_token, refresh_token, expires_in, resp.get("data", {}).get("scopes", SCOPES))

        voice_resp = ipc.send_recv({
            "nonce": str(uuid.uuid4()),
            "cmd":   "GET_SELECTED_VOICE_CHANNEL",
            "args":  {}
        })
        result["voice_active"] = voice_resp.get("data") is not None
        log.info(f"Voice active: {result['voice_active']}")

        settings_resp = ipc.send_recv({
            "nonce": str(uuid.uuid4()),
            "cmd":   "GET_VOICE_SETTINGS",
            "args":  {}
        })
        settings = settings_resp.get("data", {})
        result["muted"]    = settings.get("mute", False)
        result["deafened"] = settings.get("deaf", False)
        log.info(f"Muted: {result['muted']}  Deafened: {result['deafened']}")

    except Exception as e:
        log.error(f"Unexpected error: {type(e).__name__}: {e}")
    finally:
        ipc.close()

    return result


def main():
    try:
        result = check_discord_state()
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        log.critical(f"Fatal error in main: {e}")
        print(json.dumps({"voice_active": False, "muted": False, "deafened": False}))
        sys.exit(0)


if __name__ == "__main__":
    main()
