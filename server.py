#!/usr/bin/env python3
import asyncio
import json
import http.server
import threading
import time
import os
import sys
import platform
import socket
import subprocess
import websockets

SYSTEM = platform.system()  # 'Darwin' (macOS) or 'Linux'
HTTP_PORT = int(os.environ.get("HTTP_PORT", 8765))
WS_PORT = int(os.environ.get("WS_PORT", 8766))

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()

LOCAL_IP = get_ip()
if SYSTEM == "Darwin":
    try:
        HOSTNAME = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    except Exception:
        HOSTNAME = socket.gethostname()
else:
    HOSTNAME = socket.gethostname()

LOCAL_URL = f"http://{LOCAL_IP}:{HTTP_PORT}"
MDNS_URL = f"http://{HOSTNAME}.local:{HTTP_PORT}"

# Generate QR code png
import tempfile
QR_PATH = os.path.join(tempfile.gettempdir(), f"gamepad_qr_{os.getuid() if hasattr(os, 'getuid') else '0'}.png")
def generate_qr():
    try:
        subprocess.run(["qrencode", "-o", QR_PATH, "-s", "8", "-m", "2", LOCAL_URL], check=True)
    except Exception:
        pass

generate_qr()

# --- BACKEND IMPLEMENTATIONS ---
if SYSTEM == "Linux":
    import evdev
    from evdev import ecodes, AbsInfo

    GAMEPAD_CAP = {
        ecodes.EV_KEY: [
            ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y,
            ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_TL2, ecodes.BTN_TR2,
            ecodes.BTN_SELECT, ecodes.BTN_START, ecodes.BTN_MODE,
            ecodes.BTN_THUMBL, ecodes.BTN_THUMBR,
            ecodes.BTN_DPAD_UP, ecodes.BTN_DPAD_DOWN, ecodes.BTN_DPAD_LEFT, ecodes.BTN_DPAD_RIGHT
        ],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
            (ecodes.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
            (ecodes.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
            (ecodes.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)),
            (ecodes.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
            (ecodes.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
            (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
        ]
    }

    BUTTON_MAP = {
        'cross': ecodes.BTN_A,
        'circle': ecodes.BTN_B,
        'square': ecodes.BTN_X,
        'triangle': ecodes.BTN_Y,
        'l1': ecodes.BTN_TL,
        'r1': ecodes.BTN_TR,
        'l2': ecodes.BTN_TL2,
        'r2': ecodes.BTN_TR2,
        'select': ecodes.BTN_SELECT,
        'start': ecodes.BTN_START,
        'l3': ecodes.BTN_THUMBL,
        'r3': ecodes.BTN_THUMBR,
        'up': ecodes.BTN_DPAD_UP,
        'down': ecodes.BTN_DPAD_DOWN,
        'left': ecodes.BTN_DPAD_LEFT,
        'right': ecodes.BTN_DPAD_RIGHT,
    }

    class PlayerGamepad:
        def __init__(self, slot):
            self.slot = slot
            self.dpad_state = {'up': 0, 'down': 0, 'left': 0, 'right': 0}
            self.stick_state = {'lup': False, 'ldown': False, 'lleft': False, 'lright': False}
            self.ui = evdev.UInput(
                GAMEPAD_CAP,
                name=f"Microsoft X-Box 360 pad (P{slot})",
                vendor=0x045e,
                product=0x028e,
                version=0x0110
            )
            print(f"[GAMEPAD] Player {slot} registered at {self.ui.device.path}")

        def handle_button(self, key, is_down):
            val = 1 if is_down else 0
            if key in BUTTON_MAP:
                self.ui.write(ecodes.EV_KEY, BUTTON_MAP[key], val)
                if key in self.dpad_state:
                    self.dpad_state[key] = val
                    hat_x = self.dpad_state['right'] - self.dpad_state['left']
                    hat_y = self.dpad_state['down'] - self.dpad_state['up']
                    self.ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, hat_x)
                    self.ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, hat_y)
                if key == 'l2':
                    self.ui.write(ecodes.EV_ABS, ecodes.ABS_Z, 255 if is_down else 0)
                elif key == 'r2':
                    self.ui.write(ecodes.EV_ABS, ecodes.ABS_RZ, 255 if is_down else 0)
                self.ui.syn()
            elif key in self.stick_state:
                self.stick_state[key] = is_down
                sx = 0
                sy = 0
                if self.stick_state['lleft']: sx -= 32767
                if self.stick_state['lright']: sx += 32767
                if self.stick_state['lup']: sy -= 32767
                if self.stick_state['ldown']: sy += 32767
                self.ui.write(ecodes.EV_ABS, ecodes.ABS_X, sx)
                self.ui.write(ecodes.EV_ABS, ecodes.ABS_Y, sy)
                self.ui.syn()

        def handle_stick(self, x, y):
            cx = max(-1.0, min(1.0, float(x)))
            cy = max(-1.0, min(1.0, float(y)))
            val_x = int(cx * 32767)
            val_y = int(cy * 32767)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_X, val_x)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_Y, val_y)
            self.ui.syn()

        def close(self):
            print(f"[GAMEPAD] Player {self.slot} disconnected")
            for btn in BUTTON_MAP.values():
                self.ui.write(ecodes.EV_KEY, btn, 0)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_X, 0)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_Y, 0)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, 0)
            self.ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, 0)
            self.ui.syn()
            self.ui.close()

elif SYSTEM == "Darwin":
    import ctypes
    c = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
    cf = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    c.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    c.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    c.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    c.CGEventSetFlags.restype = None
    c.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    c.CGEventPost.restype = None
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease.restype = None

    MAC_KEY_MAP = {
        'up': 126,        # Up Arrow
        'down': 125,      # Down Arrow
        'left': 123,      # Left Arrow
        'right': 124,     # Right Arrow
        'triangle': 34,   # I
        'circle': 37,     # L
        'cross': 40,      # K
        'square': 38,     # J
        'l1': 12,         # Q
        'r1': 14,         # E
        'l2': 18,         # 1
        'r2': 20,         # 3
        'l3': 19,         # 2
        'r3': 21,         # 4
        'select': 51,     # Backspace
        'start': 36,      # Return
        'lup': 13,        # W
        'ldown': 1,       # S
        'lleft': 0,       # A
        'lright': 2       # D
    }

    def mac_send_key(key_name, is_down):
        if key_name in MAC_KEY_MAP:
            code = MAC_KEY_MAP[key_name]
            evt = c.CGEventCreateKeyboardEvent(None, code, is_down)
            if evt:
                c.CGEventSetFlags(evt, 0)
                c.CGEventPost(0, evt)  # kCGHIDEventTap
                cf.CFRelease(evt)

    class PlayerGamepad:
        def __init__(self, slot):
            self.slot = slot
            self.analog_state = {'lup': False, 'ldown': False, 'lleft': False, 'lright': False}
            print(f"[GAMEPAD-MAC] Player {slot} connected (Keyboard emulation)")

        def handle_button(self, key, is_down):
            print(f"[KEY-MAC] {key} down={is_down}", flush=True)
            mac_send_key(key, is_down)

        def handle_stick(self, x, y):
            cx = max(-1.0, min(1.0, float(x)))
            cy = max(-1.0, min(1.0, float(y)))
            thresh = 0.35
            dirs = {
                'lleft': cx < -thresh,
                'lright': cx > thresh,
                'lup': cy < -thresh,
                'ldown': cy > thresh
            }
            for d, state in dirs.items():
                if state != self.analog_state[d]:
                    self.analog_state[d] = state
                    mac_send_key(d, state)

        def close(self):
            for k in list(MAC_KEY_MAP.keys()):
                mac_send_key(k, False)
            for d in list(self.analog_state.keys()):
                self.analog_state[d] = False
            print(f"[GAMEPAD-MAC] Player {self.slot} disconnected")

available_slots = [1, 2, 3, 4]
slots_lock = threading.Lock()

HTML_CONTENT = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Gamepad ({SYSTEM})</title>
<style>
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
    -webkit-touch-callout: none;
}}
html, body {{
    background: #090a10;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
    position: fixed;
    overscroll-behavior: none;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}}
.header {{
    height: 48px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 16px;
    background: rgba(255,255,255,0.03);
    border-bottom: 1px solid rgba(255,255,255,0.08);
}}
.status {{
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 500;
}}
.status-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #ef4444;
}}
.status-dot.online {{
    background: #10b981;
    box-shadow: 0 0 10px #10b981;
}}
.hdr-btns {{
    display: flex;
    gap: 8px;
}}
.fs-btn {{
    background: #2563eb;
    border: none;
    color: #fff;
    padding: 8px 14px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
}}
.qr-btn {{
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    color: #cbd5e1;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    text-decoration: none;
    display: flex;
    align-items: center;
}}
.triggers {{
    display: flex;
    justify-content: space-between;
    padding: 8px 24px 0 24px;
}}
.trig-group {{
    display: flex;
    gap: 12px;
}}
.btn-trigger {{
    width: 80px;
    height: 44px;
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    color: #cbd5e1;
    font-weight: 700;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.main-area {{
    flex: 1;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 32px 20px 32px;
}}
.left-zone {{
    position: relative;
    width: 170px;
    height: 170px;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.dpad {{
    position: relative;
    width: 170px;
    height: 170px;
}}
.analog-view {{
    position: relative;
    width: 170px;
    height: 170px;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.dpad-btn {{
    position: absolute;
    width: 54px;
    height: 54px;
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    color: #94a3b8;
}}
.dpad-up {{ top: 0; left: 58px; }}
.dpad-down {{ bottom: 0; left: 58px; }}
.dpad-left {{ top: 58px; left: 0; }}
.dpad-right {{ top: 58px; right: 0; }}
.dpad-center {{
    position: absolute;
    top: 58px;
    left: 58px;
    width: 54px;
    height: 54px;
    background: rgba(255,255,255,0.04);
}}
.center-controls {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
}}
.mode-toggle-btn {{
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 20px;
    padding: 7px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    outline: none;
    user-select: none;
    -webkit-user-select: none;
}}
.mode-toggle-btn:active {{
    background: rgba(255,255,255,0.15);
    transform: scale(0.96);
}}
.mode-led {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #334155;
    transition: all 0.2s ease;
}}
.mode-led.on {{
    background: #ef4444;
    box-shadow: 0 0 10px #ef4444, 0 0 4px #f87171;
}}
.mode-state {{
    font-size: 11px;
    color: #94a3b8;
    font-weight: 700;
}}
.mode-led.on ~ .mode-state {{
    color: #f87171;
}}
.menu-btn-group {{
    display: flex;
    gap: 20px;
}}
.menu-btn {{
    width: 72px;
    height: 32px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 16px;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    letter-spacing: 1px;
}}
.analog-area {{
    width: 154px;
    height: 154px;
    background: radial-gradient(circle, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 70%, transparent 100%);
    border: 2px dashed rgba(255,255,255,0.18);
    border-radius: 50%;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.analog-knob {{
    width: 64px;
    height: 64px;
    background: radial-gradient(circle at 35% 35%, #38bdf8 0%, #0284c7 60%, #0369a1 100%);
    border: 2px solid rgba(255,255,255,0.3);
    border-radius: 50%;
    position: absolute;
    box-shadow: 0 6px 18px rgba(2, 132, 199, 0.45);
    pointer-events: none;
    transition: transform 0.04s ease-out;
}}
.actions {{
    position: relative;
    width: 170px;
    height: 170px;
}}
.action-btn {{
    position: absolute;
    width: 54px;
    height: 54px;
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    font-weight: 900;
}}
.act-triangle {{ top: 0; left: 58px; color: #2dd4bf; }}
.act-circle {{ top: 58px; right: 0; color: #f43f5e; }}
.act-cross {{ bottom: 0; left: 58px; color: #38bdf8; }}
.act-square {{ top: 58px; left: 0; color: #ec4899; }}

.active {{
    background: rgba(255,255,255,0.3) !important;
    transform: scale(0.94);
}}
</style>
</head>
<body>
<div class="header">
    <div class="status">
        <div id="dot" class="status-dot"></div>
        <span id="stext">Conectando...</span>
    </div>
    <div class="hdr-btns">
        <a href="/qr" class="qr-btn" id="qr-btn">QR</a>
        <button id="fs-btn" class="fs-btn">Pantalla Completa</button>
    </div>
</div>

<div class="triggers">
    <div class="trig-group">
        <div class="btn-trigger" data-key="l2">L2</div>
        <div class="btn-trigger" data-key="l1">L1</div>
    </div>
    <div class="trig-group">
        <div class="btn-trigger" data-key="r1">R1</div>
        <div class="btn-trigger" data-key="r2">R2</div>
    </div>
</div>

<div class="main-area">
    <div class="left-zone" id="left-zone">
        <div class="dpad" id="dpad-view">
            <div class="dpad-btn dpad-up" data-key="up">▲</div>
            <div class="dpad-btn dpad-left" data-key="left">◀</div>
            <div class="dpad-center"></div>
            <div class="dpad-btn dpad-right" data-key="right">▶</div>
            <div class="dpad-btn dpad-down" data-key="down">▼</div>
        </div>
        <div class="analog-view" id="analog-view" style="display: none;">
            <div class="analog-area" id="analog">
                <div class="analog-knob" id="knob"></div>
            </div>
        </div>
    </div>

    <div class="center-controls">
        <button class="mode-toggle-btn" id="mode-btn">
            <span class="mode-led" id="mode-led"></span>
            <span>ANALOG</span>
            <span class="mode-state" id="mode-state">FLECHAS</span>
        </button>
        <div class="menu-btn-group">
            <div class="menu-btn" data-key="select">SELECT</div>
            <div class="menu-btn" data-key="start">START</div>
        </div>
    </div>

    <div class="actions">
        <div class="action-btn act-triangle" data-key="triangle">▲</div>
        <div class="action-btn act-square" data-key="square">■</div>
        <div class="action-btn act-circle" data-key="circle">●</div>
        <div class="action-btn act-cross" data-key="cross">✕</div>
    </div>
</div>

<script>
let ws;
const dot = document.getElementById('dot');
const stext = document.getElementById('stext');
const WS_PORT = {WS_PORT};

function connect() {{
    const host = window.location.hostname || 'localhost';
    ws = new WebSocket('ws://' + host + ':' + WS_PORT);
    ws.onopen = () => {{
        dot.classList.add('online');
        stext.textContent = 'Conectado ({SYSTEM})';
    }};
    ws.onmessage = (e) => {{
        try {{
            const msg = JSON.parse(e.data);
            if (msg.type === 'init') {{
                const p = msg.player;
                stext.textContent = 'Jugador ' + p + ' ({SYSTEM})';
                const colors = ['#38bdf8', '#f43f5e', '#10b981', '#fbbf24'];
                const col = colors[p - 1] || '#10b981';
                dot.style.background = col;
                dot.style.boxShadow = '0 0 10px ' + col;
            }} else if (msg.type === 'full') {{
                stext.textContent = 'Servidor lleno';
                dot.classList.remove('online');
            }}
        }} catch(err) {{}}
    }};
    ws.onclose = () => {{
        dot.classList.remove('online');
        dot.style.background = '#ef4444';
        dot.style.boxShadow = 'none';
        stext.textContent = 'Reconectando...';
        setTimeout(connect, 1000);
    }};
}}
connect();

function emit(msg) {{
    if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify(msg));
    }}
}}

function emitKey(key, down) {{
    emit({{ key, down }});
    if (down) {{
        try {{
            if (navigator.vibrate) navigator.vibrate(12);
        }} catch(err) {{}}
    }}
}}

let lastStickTime = 0;
let lastStickX = 0;
let lastStickY = 0;

function emitStick(x, y) {{
    if (x === 0 && y === 0) {{
        lastStickX = 0;
        lastStickY = 0;
        emit({{ type: 'stick', x: 0, y: 0 }});
        return;
    }}
    const dx = Math.abs(x - lastStickX);
    const dy = Math.abs(y - lastStickY);
    if (dx < 0.04 && dy < 0.04) {{
        return;
    }}
    const now = performance.now();
    if (now - lastStickTime < 33 && dx < 0.2 && dy < 0.2) {{
        return;
    }}
    lastStickTime = now;
    lastStickX = x;
    lastStickY = y;
    emit({{ type: 'stick', x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100 }});
}}

let currentMode = localStorage.getItem('gamepad_control_mode') || 'dpad';
const dpadView = document.getElementById('dpad-view');
const analogView = document.getElementById('analog-view');
const modeBtn = document.getElementById('mode-btn');
const modeLed = document.getElementById('mode-led');
const modeState = document.getElementById('mode-state');
const analog = document.getElementById('analog');
const knob = document.getElementById('knob');
let analogTouchId = null;

function setLeftMode(mode) {{
    currentMode = mode;
    if (mode === 'stick') {{
        dpadView.style.display = 'none';
        analogView.style.display = 'flex';
        modeLed.classList.add('on');
        modeState.textContent = 'STICK';
        ['up', 'down', 'left', 'right'].forEach(k => emitKey(k, false));
    }} else {{
        dpadView.style.display = 'block';
        analogView.style.display = 'none';
        modeLed.classList.remove('on');
        modeState.textContent = 'FLECHAS';
        resetAnalog();
    }}
    localStorage.setItem('gamepad_control_mode', mode);
}}

function toggleMode(e) {{
    if (e) {{
        e.preventDefault();
        e.stopPropagation();
    }}
    const newMode = (currentMode === 'dpad') ? 'stick' : 'dpad';
    setLeftMode(newMode);
    try {{ if (navigator.vibrate) navigator.vibrate(20); }} catch(err) {{}}
}}

modeBtn.addEventListener('pointerdown', toggleMode);
setLeftMode(currentMode);

const activeTouches = new Map();
let dpadTouchId = null;
let currentDpadKey = null;

function getDpadKey(x, y) {{
    const rect = dpadView.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = x - cx;
    const dy = y - cy;
    const dist = Math.hypot(dx, dy);
    if (dist < 15 || dist > rect.width * 0.9) return null;
    if (Math.abs(dx) > Math.abs(dy)) {{
        return dx > 0 ? 'right' : 'left';
    }} else {{
        return dy > 0 ? 'down' : 'up';
    }}
}}

function updateDpadHighlight(key) {{
    document.querySelectorAll('.dpad-btn').forEach(btn => {{
        if (btn.getAttribute('data-key') === key) {{
            btn.classList.add('active');
        }} else {{
            btn.classList.remove('active');
        }}
    }});
}}

function handleDpadMove(t) {{
    const key = getDpadKey(t.clientX, t.clientY);
    if (key !== currentDpadKey) {{
        if (currentDpadKey) emitKey(currentDpadKey, false);
        if (key) emitKey(key, true);
        currentDpadKey = key;
        updateDpadHighlight(key);
    }}
}}

function getKeyElementFromPoint(x, y) {{
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    return el.closest('[data-key]');
}}

window.addEventListener('touchstart', (e) => {{
    if (e.target.closest('#fs-btn') || e.target.closest('#qr-btn') || e.target.closest('#mode-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];

        if (currentMode === 'stick') {{
            const aRect = analog.getBoundingClientRect();
            if (t.clientX >= aRect.left && t.clientX <= aRect.right &&
                t.clientY >= aRect.top && t.clientY <= aRect.bottom) {{
                analogTouchId = t.identifier;
                handleAnalogMove(t);
                continue;
            }}
        }} else {{
            const dRect = dpadView.getBoundingClientRect();
            if (t.clientX >= dRect.left && t.clientX <= dRect.right &&
                t.clientY >= dRect.top && t.clientY <= dRect.bottom) {{
                dpadTouchId = t.identifier;
                handleDpadMove(t);
                continue;
            }}
        }}

        const btn = getKeyElementFromPoint(t.clientX, t.clientY);
        if (btn) {{
            const key = btn.getAttribute('data-key');
            btn.classList.add('active');
            activeTouches.set(t.identifier, {{ key, btn }});
            emitKey(key, true);
        }}
    }}
}}, {{ passive: false }});

window.addEventListener('touchmove', (e) => {{
    if (e.target.closest('#fs-btn') || e.target.closest('#qr-btn') || e.target.closest('#mode-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];
        if (t.identifier === analogTouchId) {{
            handleAnalogMove(t);
        }} else if (t.identifier === dpadTouchId) {{
            handleDpadMove(t);
        }}
    }}
}}, {{ passive: false }});

function handleEnd(e) {{
    if (e.target.closest('#fs-btn') || e.target.closest('#qr-btn') || e.target.closest('#mode-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];
        if (t.identifier === analogTouchId) {{
            resetAnalog();
        }}
        if (t.identifier === dpadTouchId) {{
            if (currentDpadKey) {{
                emitKey(currentDpadKey, false);
                currentDpadKey = null;
            }}
            updateDpadHighlight(null);
            dpadTouchId = null;
        }}
        if (activeTouches.has(t.identifier)) {{
            const entry = activeTouches.get(t.identifier);
            if (entry.btn) entry.btn.classList.remove('active');
            emitKey(entry.key, false);
            activeTouches.delete(t.identifier);
        }}
    }}
}}

window.addEventListener('touchend', handleEnd, {{ passive: false }});
window.addEventListener('touchcancel', handleEnd, {{ passive: false }});

function handleAnalogMove(t) {{
    const rect = analog.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const dx = t.clientX - cx;
    const dy = t.clientY - cy;
    const maxR = rect.width / 2 - 8;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const clampedR = Math.min(dist, maxR);
    const angle = Math.atan2(dy, dx);
    const kx = Math.cos(angle) * clampedR;
    const ky = Math.sin(angle) * clampedR;
    knob.style.transform = `translate(${{kx}}px, ${{ky}}px)`;

    const normX = maxR > 0 ? kx / maxR : 0;
    const normY = maxR > 0 ? ky / maxR : 0;
    emitStick(normX, normY);
}}

function resetAnalog() {{
    analogTouchId = null;
    knob.style.transform = 'translate(0px, 0px)';
    emitStick(0, 0);
}}

const fsBtn = document.getElementById('fs-btn');
function toggleFS(e) {{
    if (e) {{
        e.preventDefault();
        e.stopPropagation();
    }}
    const doc = document.documentElement;
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {{
        if (doc.requestFullscreen) {{
            doc.requestFullscreen().catch(() => {{}});
        }} else if (doc.webkitRequestFullscreen) {{
            doc.webkitRequestFullscreen();
        }}
        fsBtn.textContent = 'Salir Completa';
    }} else {{
        if (document.exitFullscreen) {{
            document.exitFullscreen().catch(() => {{}});
        }} else if (document.webkitExitFullscreen) {{
            document.webkitExitFullscreen();
        }}
        fsBtn.textContent = 'Pantalla Completa';
    }}
}}
fsBtn.addEventListener('pointerdown', toggleFS);
</script>
</body>
</html>
"""

QR_PAGE_CONTENT = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Escanear Gamepad ({SYSTEM})</title>
<style>
body {{
    background: #090a10;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    box-sizing: border-box;
    text-align: center;
}}
.card {{
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 20px;
    padding: 30px;
    max-width: 360px;
    width: 100%;
}}
h1 {{
    font-size: 20px;
    margin-bottom: 8px;
}}
p {{
    color: #94a3b8;
    font-size: 13px;
    margin-bottom: 24px;
}}
.qr-box {{
    background: #fff;
    padding: 16px;
    border-radius: 14px;
    display: inline-block;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}}
.qr-box img {{
    width: 200px;
    height: 200px;
    display: block;
}}
.links {{
    margin-top: 24px;
    font-size: 12px;
    color: #38bdf8;
    display: flex;
    flex-direction: column;
    gap: 8px;
}}
.links a {{
    color: inherit;
    text-decoration: none;
}}
.btn-back {{
    margin-top: 20px;
    display: inline-block;
    background: #2563eb;
    color: #fff;
    text-decoration: none;
    padding: 10px 20px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
}}
</style>
</head>
<body>
<div class="card">
    <h1>Conectar Gamepad</h1>
    <p>Escanea con la cámara de tu celular para abrir el control.</p>
    <div class="qr-box">
        <img src="/qr.png" alt="Código QR Gamepad">
    </div>
    <div class="links">
        <a href="{LOCAL_URL}">{LOCAL_URL}</a>
        <a href="{MDNS_URL}">{MDNS_URL}</a>
    </div>
    <a href="/" class="btn-back">Abrir Control Aquí</a>
</div>
</body>
</html>
"""

class HTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        if self.path == "/qr":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(QR_PAGE_CONTENT.encode("utf-8"))
        elif self.path == "/qr.png":
            if os.path.exists(QR_PATH):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(QR_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def log_message(self, *args):
        pass

def start_http():
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), HTTPHandler)
    print(f"[HTTP] Listening on http://0.0.0.0:{HTTP_PORT}")
    httpd.serve_forever()

VALID_BUTTONS = {
    'up', 'down', 'left', 'right',
    'triangle', 'circle', 'cross', 'square',
    'l1', 'r1', 'l2', 'r2', 'l3', 'r3',
    'select', 'start'
}

async def ws_handler(websocket):
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    slot = None
    with slots_lock:
        if available_slots:
            slot = available_slots.pop(0)

    if not slot:
        print(f"[WS] Rejecting {client_ip}: Server full (max 4 players)")
        try:
            await websocket.send(json.dumps({"type": "full", "message": "Servidor lleno"}))
            await websocket.close()
        except Exception:
            pass
        return

    player = None
    try:
        player = PlayerGamepad(slot)
    except Exception as e:
        print(f"[GAMEPAD ERR] Cannot create backend for Player {slot}: {e}")
        with slots_lock:
            available_slots.insert(0, slot)
            available_slots.sort()
        try:
            await websocket.close()
        except Exception:
            pass
        return

    print(f"[WS] Client connected from {client_ip} as Player {slot}")
    try:
        await websocket.send(json.dumps({"type": "init", "player": slot}))
        async for message in websocket:
            try:
                data = json.loads(message)
                mtype = data.get("type")
                if mtype == "stick":
                    x = data.get("x", 0)
                    y = data.get("y", 0)
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        player.handle_stick(x, y)
                else:
                    key = data.get("key")
                    down = bool(data.get("down", False))
                    if key in VALID_BUTTONS:
                        player.handle_button(key, down)
            except Exception as e:
                print(f"[WS JSON ERR] P{slot}: {e}")
    except Exception as e:
        print(f"[WS CLIENT ERR] P{slot}: {e}")
    finally:
        if player:
            player.close()
        with slots_lock:
            available_slots.append(slot)
            available_slots.sort()
        print(f"[WS] Player {slot} disconnected ({client_ip})")

async def start_ws():
    print(f"[WS] Listening on ws://0.0.0.0:{WS_PORT}")
    async with websockets.serve(
        ws_handler,
        "0.0.0.0",
        WS_PORT,
        ping_interval=20,
        ping_timeout=60,
        max_size=2**16
    ):
        await asyncio.Future()

def print_banner():
    print("=" * 45)
    print(f" Touch Gamepad Server ({SYSTEM})")
    print(f" URL Wi-Fi:   {LOCAL_URL}")
    print(f" URL Bonjour: {MDNS_URL}")
    print(f" Página QR:   {LOCAL_URL}/qr")
    print("=" * 45)
    try:
        res = subprocess.run(["qrencode", "-t", "UTF8", LOCAL_URL], capture_output=True, text=True)
        if res.returncode == 0:
            print(res.stdout)
    except Exception:
        pass

if __name__ == "__main__":
    print_banner()
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    try:
        asyncio.run(start_ws())
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
