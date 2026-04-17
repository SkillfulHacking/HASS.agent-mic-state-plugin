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
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

CLIENT_ID = "1494532375496097853"  # Replace with your Discord Application ID
DISCORD_RPC_PORT = 6463
DISCORD_RPC_PORTS = range(6463, 6473)   # Discord tries 6463-6472
ORIGIN = "https://streamkit.discord.com"
TIMEOUT = 5

# ── Logging (writes to %APPDATA%\hass-mic-state\plugin.log) ──────────────────

log_dir = Path(os.environ.get("APPDATA", ".")) / "hass-mic-state"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "plugin.log"

logging.basicConfig(
    filename=str(log_file),
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


# ── Core Logic ────────────────────────────────────────────────────────────────

async def find_discord_port() -> int | None:
    """Find which port Discord RPC is listening on."""
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


async def check_voice_channel() -> bool:
    """
    Connect to Discord local RPC and check if user is in a voice channel.
    Returns True if in a voice channel, False otherwise.
    """
    port = await find_discord_port()
    if port is None:
        log.warning("Discord RPC not found on any port. Is Discord running?")
        return False

    uri = f"ws://127.0.0.1:{port}/?v=1&client_id={CLIENT_ID}"

    try:
        async with websockets.connect(
            uri,
            additional_headers={"Origin": ORIGIN},
            open_timeout=TIMEOUT
        ) as ws:
            # Wait for initial READY event from Discord
            raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            data = json.loads(raw)
            log.debug(f"Initial event: cmd={data.get('cmd')} evt={data.get('evt')}")

            if data.get("evt") != "READY":
                log.warning(f"Expected READY, got: {data.get('evt')}")

            # Request current voice channel
            payload = {
                "nonce": "hass_mic_check",
                "args": {},
                "cmd": "GET_SELECTED_VOICE_CHANNEL"
            }
            await ws.send(json.dumps(payload))

            raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
            data = json.loads(raw)
            log.debug(f"Voice channel response: {json.dumps(data)}")

            # data["data"] is None when not in a channel, dict when in one
            in_channel = data.get("data") is not None
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
