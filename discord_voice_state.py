"""
HASS.agent-mic-state-plugin
Detects whether the user is currently in a Discord voice channel
via Discord's local RPC API and returns on/off for HASS.Agent.

Returns:
    stdout: "on" if in a voice channel, "off" otherwise
    exit code: 0 always (HASS.Agent expects clean exit)
"""

import asyncio
import websockets
import json
import sys
import os
import logging
import urllib.request
import urllib.parse
import uuid
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

CLIENT_ID = "1494532375496097853"
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"  # Discord Developer Portal → OAuth2
SCOPES = ["rpc", "rpc.voice.read"]
ORIGIN = "http://localhost"  # Must be registered in Developer Portal → RPC Origins
DISCORD_RPC_PORTS = range(6463, 6473)
TIMEOUT = 5

# ── Paths ─────────────────────────────────────────────────────────────────────

log_dir = Path(os.environ.get("APPDATA", ".")) / "hass-mic-state"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "plugin.log"
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
        return json.loads(token_file.read_text()).get("access_token")
    except Exception:
        return None


def save_token(access_token: str) -> None:
    token_file.write_text(json.dumps({"access_token": access_token}))


def clear_token() -> None:
    token_file.unlink(missing_ok=True)


# ── OAuth2 token exchange ─────────────────────────────────────────────────────

def exchange_code(code: str) -> str | None:
    try:
        data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
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


# ── RPC helpers ───────────────────────────────────────────────────────────────

async def find_discord_port() -> int | None:
    for port in DISCORD_RPC_PORTS:
        try:
            uri = f"ws://127.0.0.1:{port}/?v=1&client_id={CLIENT_ID}"
            async with websockets.connect(
                uri,
                additional_headers={"Origin": ORIGIN},
                open_timeout=2
            ) as ws:
                log.debug(f"Connected on port {port}")
                return port
        except Exception:
            continue
    return None


async def send_recv(ws, payload: dict) -> dict:
    await ws.send(json.dumps(payload))
    raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
    return json.loads(raw)


# ── Core logic ────────────────────────────────────────────────────────────────

async def check_voice_channel() -> bool:
    port = await find_discord_port()
    if port is None:
        log.warning("Discord RPC not found. Is Discord running?")
        return False

    uri = f"ws://127.0.0.1:{port}/?v=1&client_id={CLIENT_ID}"

    try:
        async with websockets.connect(
            uri,
            additional_headers={"Origin": ORIGIN},
            open_timeout=TIMEOUT
        ) as ws:
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT))
            log.debug(f"Initial event: {data.get('evt')}")

            access_token = load_token()

            if access_token:
                resp = await send_recv(ws, {
                    "nonce": str(uuid.uuid4()),
                    "cmd": "AUTHENTICATE",
                    "args": {"access_token": access_token}
                })
                if resp.get("evt") == "ERROR":
                    log.warning("Cached token rejected, re-authorizing")
                    clear_token()
                    access_token = None

            if not access_token:
                resp = await send_recv(ws, {
                    "nonce": str(uuid.uuid4()),
                    "cmd": "AUTHORIZE",
                    "args": {"client_id": CLIENT_ID, "scopes": SCOPES}
                })
                if resp.get("evt") == "ERROR":
                    log.error(f"Authorization failed: {resp}")
                    return False

                code = resp.get("data", {}).get("code")
                if not code:
                    log.error("No auth code in AUTHORIZE response")
                    return False

                access_token = exchange_code(code)
                if not access_token:
                    return False
                save_token(access_token)

                resp = await send_recv(ws, {
                    "nonce": str(uuid.uuid4()),
                    "cmd": "AUTHENTICATE",
                    "args": {"access_token": access_token}
                })
                if resp.get("evt") == "ERROR":
                    log.error(f"Authentication failed after exchange: {resp}")
                    clear_token()
                    return False

            resp = await send_recv(ws, {
                "nonce": str(uuid.uuid4()),
                "cmd": "GET_SELECTED_VOICE_CHANNEL",
                "args": {}
            })
            log.debug(f"Voice channel response: {json.dumps(resp)}")

            in_channel = resp.get("data") is not None
            log.info(f"Voice channel active: {in_channel}")
            return in_channel

    except asyncio.TimeoutError:
        log.error("Timeout waiting for Discord RPC response")
        return False
    except websockets.exceptions.ConnectionClosedError as e:
        log.error(f"Discord closed connection: {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error: {type(e).__name__}: {e}")
        return False


def main():
    try:
        result = asyncio.run(check_voice_channel())
        print("on" if result else "off")
        sys.exit(0)
    except Exception as e:
        log.critical(f"Fatal error in main: {e}")
        print("off")
        sys.exit(0)


if __name__ == "__main__":
    main()
