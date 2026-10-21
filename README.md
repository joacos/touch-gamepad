# Touch Gamepad for Linux

Virtual touch gamepad server running on Linux via `/dev/uinput` and WebSockets.
Allows using a smartphone browser (via Wi-Fi or Tailscale) as a physical Xbox 360 controller for emulators (PCSX2, RetroArch, RPCS3, Dolphin) and native Linux games.

## Features
- **Zero latency native input**: Generates kernel-level joystick events (`/dev/input/js*`) via `evdev.UInput`.
- **Multi-Touch support**: Press multiple face buttons, triggers, and D-Pad simultaneously.
- **True 360° Analog Stick**: Smooth floating-point stick input with auto-centering.
- **Haptic feedback**: Short vibration pulses on touch press.
- **Dedicated ports**:
  - HTTP Server: `8765`
  - WebSocket Server: `8766`

## Running
```bash
python3 server.py
```

## Systemd User Service
Install service:
```bash
mkdir -p ~/.config/systemd/user
cp gamepad.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gamepad
```
