#!/usr/bin/env python3
import asyncio
import json
import http.server
import threading
import os
import sys
import websockets
import evdev
from evdev import ecodes, AbsInfo

HTTP_PORT = int(os.environ.get("HTTP_PORT", 8765))
WS_PORT = int(os.environ.get("WS_PORT", 8766))

# Define virtual Xbox 360 controller capabilities
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

# Player slot management (1-4)
available_slots = [1, 2, 3, 4]
slots_lock = threading.Lock()

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
        self.ui.close()

HTML_CONTENT = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Gamepad Thinkpad</title>
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
.fs-btn {{
    background: #2563eb;
    border: none;
    color: #fff;
    padding: 8px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
}}
.fs-btn:active {{
    background: #1d4ed8;
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
.dpad {{
    position: relative;
    width: 170px;
    height: 170px;
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
    gap: 14px;
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
    width: 130px;
    height: 130px;
    background: rgba(255,255,255,0.03);
    border: 2px dashed rgba(255,255,255,0.12);
    border-radius: 50%;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
}}
.analog-knob {{
    width: 60px;
    height: 60px;
    background: radial-gradient(circle, #38bdf8 0%, #0284c7 100%);
    border-radius: 50%;
    position: absolute;
    box-shadow: 0 4px 15px rgba(56, 189, 248, 0.4);
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
    <button id="fs-btn" class="fs-btn">Pantalla Completa</button>
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
    <div class="dpad">
        <div class="dpad-btn dpad-up" data-key="up">▲</div>
        <div class="dpad-btn dpad-left" data-key="left">◀</div>
        <div class="dpad-center"></div>
        <div class="dpad-btn dpad-right" data-key="right">▶</div>
        <div class="dpad-btn dpad-down" data-key="down">▼</div>
    </div>

    <div class="center-controls">
        <div class="menu-btn-group">
            <div class="menu-btn" data-key="select">SELECT</div>
            <div class="menu-btn" data-key="start">START</div>
        </div>
        <div class="analog-area" id="analog">
            <div class="analog-knob" id="knob"></div>
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
        stext.textContent = 'Conectado...';
    }};
    ws.onmessage = (e) => {{
        try {{
            const msg = JSON.parse(e.data);
            if (msg.type === 'init') {{
                const p = msg.player;
                stext.textContent = 'Jugador ' + p;
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
    if (down && navigator.vibrate) {{
        navigator.vibrate(12);
    }}
}}

function emitStick(x, y) {{
    emit({{ type: 'stick', x, y }});
}}

const activeTouches = new Map();
const analog = document.getElementById('analog');
const knob = document.getElementById('knob');
let analogTouchId = null;

function getKeyElementFromPoint(x, y) {{
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    return el.closest('[data-key]');
}}

window.addEventListener('touchstart', (e) => {{
    if (e.target.closest('#fs-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];
        const aRect = analog.getBoundingClientRect();
        if (t.clientX >= aRect.left && t.clientX <= aRect.right &&
            t.clientY >= aRect.top && t.clientY <= aRect.bottom) {{
            analogTouchId = t.identifier;
            handleAnalogMove(t);
            continue;
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
    if (e.target.closest('#fs-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];
        if (t.identifier === analogTouchId) {{
            handleAnalogMove(t);
        }}
    }}
}}, {{ passive: false }});

function handleEnd(e) {{
    if (e.target.closest('#fs-btn')) return;
    e.preventDefault();
    for (let i = 0; i < e.changedTouches.length; i++) {{
        const t = e.changedTouches[i];
        if (t.identifier === analogTouchId) {{
            resetAnalog();
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
fsBtn.addEventListener('click', toggleFS);
fsBtn.addEventListener('touchend', toggleFS);
</script>
</body>
</html>
"""

class HTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
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
        print(f"[GAMEPAD ERR] Cannot create uinput for Player {slot}: {e}")
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
                    player.handle_stick(data.get("x", 0), data.get("y", 0))
                else:
                    key = data.get("key")
                    down = data.get("down", False)
                    if key:
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
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()

if __name__ == "__main__":
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    try:
        asyncio.run(start_ws())
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
