# Privacy Policy

**Project:** HASS.agent-mic-state-plugin  
**Effective Date:** April 16, 2026  
**Last Updated:** April 16, 2026

---

## Overview

HASS.agent-mic-state-plugin is an open source, locally-run tool that integrates Discord voice channel state with Home Assistant via HASS.Agent. This policy describes what data the plugin accesses, how it is used, and what is never collected or transmitted.

---

## Data Accessed

The plugin accesses the following data through Discord's local RPC API:

- **Voice channel state** — whether the user is currently connected to a Discord voice channel (on/off)

This data is read locally on the user's own machine. No data is transmitted to any external server, cloud service, or third party.

---

## Data We Do Not Collect

The plugin does **not** collect, store, log, or transmit any of the following:

- User identity or Discord account information
- Voice or audio content
- Message content of any kind
- Server, channel, or guild names
- Contact lists or friend lists
- Usage analytics or telemetry
- Any personally identifiable information (PII)

---

## How Data Is Used

The sole purpose of the data accessed is to produce a binary on/off sensor state that is passed to a locally-hosted Home Assistant instance on the same network as the user's machine. This state is used exclusively to trigger local home automation routines defined by the user.

---

## Data Storage

No data is stored by this plugin. The plugin reads voice channel state at the time of execution and immediately discards it after passing the result to the local Home Assistant sensor. No logs, databases, or persistent files are created.

---

## Third-Party Services

This plugin communicates only with:

- **Discord** — via the local RPC API running on the user's own machine (localhost)
- **Home Assistant** — via the local HASS.Agent integration on the user's own network

No internet-facing APIs, analytics services, or third-party platforms are contacted.

---

## User Control

Users have full control over this plugin at all times:

- The plugin runs only when explicitly executed or scheduled by the user
- Discord RPC authorization can be revoked at any time via Discord → User Settings → Authorized Apps
- The plugin can be uninstalled by removing the associated files

---

## Children's Privacy

This plugin does not target or knowingly collect any information from children under the age of 13.

---

## Changes to This Policy

If this policy is updated, the updated version will be committed to this repository with a revised **Last Updated** date. Continued use of the plugin after changes constitutes acceptance of the revised policy.

---

## Contact

This project is maintained as open source software. For questions or concerns, please open an issue in the [GitHub repository](https://github.com/SkillfulHacking/HASS.agent-mic-state-plugin).
