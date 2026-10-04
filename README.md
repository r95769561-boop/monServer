---
title: MON Control Server
emoji: ⚡
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# Microcontroller Overlay Network (MON) — Control & Signaling Server

Zero-trust, peer-to-peer (P2P), end-to-end encrypted (E2EE) IoT overlay network control server.

## Features
- **P2P Signaling**: STUN candidate exchange and X25519 / Post-Quantum hybrid key exchange.
- **Dynamic Resources**: Switch, control sliders, and sensor telemetry values.
- **Current Sensing & Feedback**: Real-time current sensing with automatic detection for mains power loss (ESP32 running on battery backup).
- **Web PWA Control App**: Built-in glassmorphic dashboard hosted at `/app`.

## Accessing the Web Dashboard
Visit:
`https://<your-space-name>.hf.space/app/`
