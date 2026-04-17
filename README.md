# HASS.agent-mic-state-plugin

A lightweight Windows plugin that detects whether you are currently in a Discord voice channel and exposes that state as an `on`/`off` sensor in [HASS.Agent](https://github.com/hass-agent/HASS.Agent) for Home Assistant.

---

## What It Does

- Connects to Discord's local RPC API on your machine
- Returns `on` if you are in a voice channel, `off` if you are not
- Designed to be called directly as a PowerShell sensor in HASS.Agent
- No cloud services, no data collection, no telemetry

---

## Requirements

- Windows 10 or later (64-bit)
- Discord desktop app running
- [HASS.Agent](https://github.com/hass-agent/HASS.Agent) installed and connected to Home Assistant

---

## Installation

1. Download the latest installer from [Releases](https://github.com/SkillfulHacking/HASS.agent-mic-state-plugin/releases)
2. Run `HASS.agent-mic-state-plugin-setup-v1.0.0.exe`
3. Follow the installer prompts
4. The install path will be shown and copied to your clipboard on completion

---

## HASS.Agent Setup

After installation, add a new sensor in HASS.Agent:

| Field | Value |
|---|---|
| Type | PowerShell Sensor |
| Name | `discord_voice_active` |
| Command | `& "C:\Program Files\HASS.agent-mic-state-plugin\discord_voice_state.exe"` |
| Update interval | 10 seconds |

The sensor will appear in Home Assistant as `binary_sensor.desktop_<id>_discord_voice_active` with states `on` / `off`.

---

## Discord Authorization

The first time the plugin runs, Discord will display an authorization prompt. Click **Authorize** to allow the plugin to read your voice channel state. This authorization can be revoked at any time via:

**Discord → User Settings → Authorized Apps → HASS.agent-mic-state-plugin → Deauthorize**

---

## Home Assistant Automation Example

Turn an RGB light green when you join a voice channel:

```yaml
alias: Office RGB - Discord Voice Active
trigger:
  - platform: state
    entity_id: binary_sensor.desktop_<id>_discord_voice_active
    to: "on"
action:
  - service: scene.create
    data:
      scene_id: pre_call_office_rgb
      snapshot_entities:
        - light.office_rgb_motion
  - service: light.turn_on
    target:
      entity_id: light.office_rgb_motion
    data:
      rgb_color: [0, 255, 0]
      brightness: 255
```

```yaml
alias: Office RGB - Discord Voice Ended
trigger:
  - platform: state
    entity_id: binary_sensor.desktop_<id>_discord_voice_active
    to: "off"
action:
  - service: scene.turn_on
    target:
      entity_id: scene.pre_call_office_rgb
```

---

## Logs

Plugin logs are written to:
```
%APPDATA%\hass-mic-state\plugin.log
```

---

## Building From Source

### Prerequisites

```bash
pip install websockets pyinstaller
```

### Build EXE

```bash
pyinstaller discord_voice_state.spec
```

Output: `dist\discord_voice_state.exe`

### Build Installer

1. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php)
2. Open `installer\installer.iss`
3. Click **Build → Compile**

Output: `installer\installer_output\HASS.agent-mic-state-plugin-setup-v1.0.0.exe`

---

## Project Structure

```
HASS.agent-mic-state-plugin/
├── discord_voice_state.py      # Core plugin script
├── discord_voice_state.spec    # PyInstaller build spec
├── version_info.txt            # Windows EXE metadata
├── installer/
│   └── installer.iss           # Inno Setup installer script
├── LICENSE
├── PRIVACY_POLICY.md
├── TERMS_OF_SERVICE.md
└── README.md
```

---

## Legal

- [Privacy Policy](PRIVACY_POLICY.md)
- [Terms of Service](TERMS_OF_SERVICE.md)
- [MIT License](LICENSE)

---

## Contributing

Issues and pull requests are welcome. This project is intended to remain simple and focused — a single-purpose sensor with no scope creep.
