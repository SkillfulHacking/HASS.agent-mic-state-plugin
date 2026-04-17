"""
HASS.agent-mic-state-plugin
Connects to Discord via IPC named pipe to read voice channel state
and game activity for use as a HASS.Agent sensor.

Returns:
    stdout: JSON with voice_active (bool) and activity (object or null)
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
SCOPES    = ["rpc", "rpc.voice.read", "identify", "guilds"]
MAX_GUILDS_TO_CHECK = 5

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

def load_token() -> str | None:
    try:
        data = json.loads(token_file.read_text())
        if not set(SCOPES).issubset(set(data.get("scopes", []))):
            log.info("Cached token missing required scopes, re-authorizing")
            return None
        return data.get("access_token")
    except Exception:
        return None


def save_token(access_token: str, scopes: list) -> None:
    token_file.write_text(json.dumps({"access_token": access_token, "scopes": scopes}))


def clear_token() -> None:
    token_file.unlink(missing_ok=True)

# ── OAuth2 token exchange (public client — no secret) ─────────────────────────

def exchange_code(code: str) -> str | None:
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
            return json.loads(resp.read()).get("access_token")
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

# ── Discord REST ──────────────────────────────────────────────────────────────

def rest_get(path: str, access_token: str) -> dict | list | None:
    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10{path}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.error(f"REST GET {path} failed: {e}")
        return None

# ── Activity detection ────────────────────────────────────────────────────────

def get_current_activity(ipc: DiscordIPC, access_token: str, user_id: str) -> dict | None:
    guilds = rest_get("/users/@me/guilds", access_token)
    if not guilds:
        return None

    for guild in guilds[:MAX_GUILDS_TO_CHECK]:
        try:
            resp = ipc.send_recv({
                "nonce": str(uuid.uuid4()),
                "cmd":   "GET_GUILD",
                "args":  {"guild_id": guild["id"], "timeout": 1000}
            })
            for member in resp.get("data", {}).get("members", []):
                if member.get("user", {}).get("id") != user_id:
                    continue
                for activity in member.get("activities", []):
                    if activity.get("type") == 0:  # 0 = Playing
                        return {
                            "name":    activity.get("name"),
                            "details": activity.get("details"),
                            "state":   activity.get("state"),
                        }
        except Exception as e:
            log.debug(f"GET_GUILD failed for {guild.get('id')}: {e}")

    return None

# ── Core logic ────────────────────────────────────────────────────────────────

def check_discord_state() -> dict:
    result = {"voice_active": False, "muted": False, "deafened": False, "activity": None}

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

            access_token = exchange_code(code)
            if not access_token:
                return result

            resp = ipc.send_recv({
                "nonce": str(uuid.uuid4()),
                "cmd":   "AUTHENTICATE",
                "args":  {"access_token": access_token}
            })
            if resp.get("evt") == "ERROR":
                log.error(f"AUTHENTICATE failed: {resp.get('data', {}).get('message')}")
                clear_token()
                return result

            save_token(access_token, resp.get("data", {}).get("scopes", SCOPES))

        user_id = resp.get("data", {}).get("user", {}).get("id")

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

        if user_id:
            result["activity"] = get_current_activity(ipc, access_token, user_id)
        log.info(f"Activity: {result['activity']}")

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
        print(json.dumps({"voice_active": False, "muted": False, "deafened": False, "activity": None}))
        sys.exit(0)


if __name__ == "__main__":
    main()
