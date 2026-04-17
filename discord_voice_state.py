"""
HASS.agent-mic-state-plugin
Detects Discord voice channel state and current game activity
via Discord's local RPC API for use as a HASS.Agent sensor.

Returns:
    stdout: JSON with voice_active (bool) and activity (object or null)
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
import hashlib
import base64
import secrets
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

CLIENT_ID = "1494532375496097853"
SCOPES = ["rpc", "rpc.voice.read", "identify", "guilds"]
ORIGIN = "http://localhost"  # Must be registered in Developer Portal → OAuth2 → RPC Origins
DISCORD_RPC_PORTS = range(6463, 6473)
TIMEOUT = 5
MAX_GUILDS_TO_CHECK = 5  # cap to keep polling fast

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

# ── PKCE ──────────────────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return code_verifier, code_challenge

# ── Token cache ───────────────────────────────────────────────────────────────

def load_token() -> str | None:
    try:
        data = json.loads(token_file.read_text())
        cached_scopes = set(data.get("scopes", []))
        if not set(SCOPES).issubset(cached_scopes):
            log.info("Cached token missing required scopes, re-authorizing")
            return None
        return data.get("access_token")
    except Exception:
        return None


def save_token(access_token: str, scopes: list) -> None:
    token_file.write_text(json.dumps({"access_token": access_token, "scopes": scopes}))


def clear_token() -> None:
    token_file.unlink(missing_ok=True)

# ── OAuth2 token exchange (public client / PKCE — no secret required) ─────────

def exchange_code(code: str, code_verifier: str) -> str | None:
    try:
        data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
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

# ── Discord REST helpers ───────────────────────────────────────────────────────

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

# ── Activity detection ────────────────────────────────────────────────────────

async def get_current_activity(ws, access_token: str, user_id: str) -> dict | None:
    """
    Checks the user's guilds via REST, then calls GET_GUILD via local RPC
    to find the current user's game activity (type 0 = Playing).
    Capped at MAX_GUILDS_TO_CHECK to keep polling fast.
    Note: GET_GUILD including member presence needs verification after review.
    """
    guilds = rest_get("/users/@me/guilds", access_token)
    if not guilds:
        return None

    for guild in guilds[:MAX_GUILDS_TO_CHECK]:
        try:
            resp = await send_recv(ws, {
                "nonce": str(uuid.uuid4()),
                "cmd": "GET_GUILD",
                "args": {"guild_id": guild["id"], "timeout": 1000}
            })
            members = resp.get("data", {}).get("members", [])
            for member in members:
                if member.get("user", {}).get("id") != user_id:
                    continue
                for activity in member.get("activities", []):
                    if activity.get("type") == 0:  # 0 = Playing
                        return {
                            "name": activity.get("name"),
                            "details": activity.get("details"),
                            "state": activity.get("state"),
                        }
        except Exception as e:
            log.debug(f"GET_GUILD failed for {guild.get('id')}: {e}")

    return None

# ── Core logic ────────────────────────────────────────────────────────────────

async def check_discord_state() -> dict:
    result = {"voice_active": False, "activity": None}

    port = await find_discord_port()
    if port is None:
        log.warning("Discord RPC not found. Is Discord running?")
        return result

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
                code_verifier, code_challenge = generate_pkce_pair()

                resp = await send_recv(ws, {
                    "nonce": str(uuid.uuid4()),
                    "cmd": "AUTHORIZE",
                    "args": {
                        "client_id": CLIENT_ID,
                        "scopes": SCOPES,
                        "code_challenge": code_challenge,
                        "code_challenge_method": "S256",
                    }
                })
                if resp.get("evt") == "ERROR":
                    log.error(f"Authorization failed: {resp}")
                    return result

                code = resp.get("data", {}).get("code")
                if not code:
                    log.error("No auth code in AUTHORIZE response")
                    return result

                access_token = exchange_code(code, code_verifier)
                if not access_token:
                    return result

                resp = await send_recv(ws, {
                    "nonce": str(uuid.uuid4()),
                    "cmd": "AUTHENTICATE",
                    "args": {"access_token": access_token}
                })
                if resp.get("evt") == "ERROR":
                    log.error(f"Authentication failed after exchange: {resp}")
                    clear_token()
                    return result

                granted_scopes = resp.get("data", {}).get("scopes", SCOPES)
                save_token(access_token, granted_scopes)
            else:
                resp = {"data": {}}  # auth already confirmed above

            user_id = resp.get("data", {}).get("user", {}).get("id")

            # Voice channel state
            voice_resp = await send_recv(ws, {
                "nonce": str(uuid.uuid4()),
                "cmd": "GET_SELECTED_VOICE_CHANNEL",
                "args": {}
            })
            result["voice_active"] = voice_resp.get("data") is not None
            log.info(f"Voice active: {result['voice_active']}")

            # Game activity
            if user_id:
                result["activity"] = await get_current_activity(ws, access_token, user_id)
            log.info(f"Activity: {result['activity']}")

    except asyncio.TimeoutError:
        log.error("Timeout waiting for Discord RPC response")
    except websockets.exceptions.ConnectionClosedError as e:
        log.error(f"Discord closed connection: {e}")
    except Exception as e:
        log.error(f"Unexpected error: {type(e).__name__}: {e}")

    return result


def main():
    try:
        result = asyncio.run(check_discord_state())
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        log.critical(f"Fatal error in main: {e}")
        print(json.dumps({"voice_active": False, "activity": None}))
        sys.exit(0)


if __name__ == "__main__":
    main()
