"""Giả lập Raspberry Pi để phát triển/test phần PC khi chưa có phần cứng.

- Kết nối /ws/pi như Pi thật, dùng CHÍNH link.py của Pi (TLS + xác thực HMAC + tin được ký);
  khóa đọc từ pc_server/data/pi.key, vân tay từ data/tls/server.crt (đèn LED, màn hình, rào in ra console)
- Phát luồng MJPEG giả của bãi xe (hình vẽ nhìn từ trên xuống) tại http://localhost:8081/stream.mjpg
- Gõ lệnh để giả lập xe, hoặc chạy --auto để xe tự ra vào ngẫu nhiên

Lệnh:  in | out | park A1 | leave A1 | fill | clear | status | quit
"""
import argparse
import json
import random
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
PC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PC_DIR))
sys.path.insert(0, str(PC_DIR.parent / "raspberry_pi"))  # dùng chung link.py + secure_channel.py của Pi thật
from link import PiLink  # noqa: E402

LAYOUT = json.loads((PC_DIR / "config" / "layout.json").read_text())
W, H = LAYOUT["frame"]["width"], LAYOUT["frame"]["height"]
SLOTS = {s["id"]: s for s in LAYOUT["slots"]}
CAR_COLORS = [(40, 40, 200), (200, 120, 30), (30, 160, 220), (60, 180, 60), (180, 60, 160), (210, 210, 210)]

cars = {}            # slot_id -> BGR color
leds = []            # trạng thái đèn nhận từ server
lock = threading.Lock()
link = None


def base_image():
    img = np.full((H, W, 3), (70, 70, 72), np.uint8)
    nodes = LAYOUT["nodes"]
    for a, b in LAYOUT.get("edges", []):  # làn đường
        cv2.line(img, tuple(nodes[a]), tuple(nodes[b]), (58, 58, 60), 70)
    for a, b in LAYOUT.get("edges", []):
        cv2.line(img, tuple(nodes[a]), tuple(nodes[b]), (120, 120, 120), 1, cv2.LINE_AA)
    for sid, s in SLOTS.items():
        pts = np.array(s["roi"], np.int32)
        cv2.polylines(img, [pts], True, (235, 235, 235), 2)
        x, y = pts.min(axis=0) + 6
        cv2.putText(img, s.get("label", str(sid)), (int(x), int(y) + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (190, 190, 190), 1, cv2.LINE_AA)
    decor = LAYOUT.get("decor", {})
    if "pillar" in decor:
        cv2.fillPoly(img, [np.array(decor["pillar"], np.int32)], (0, 220, 255))
    for key, col in (("entrance_arrow", (40, 40, 40)), ("exit_arrow", (60, 60, 230))):
        if key in decor:
            a, b = decor[key]
            cv2.arrowedLine(img, tuple(a), tuple(b), col, 6, tipLength=0.4)
    return img


BASE = base_image()


def render():
    img = BASE.copy()
    with lock:
        items = list(cars.items())
    for sid, col in items:
        pts = np.array(SLOTS[sid]["roi"], np.int32)
        x1, y1 = pts.min(axis=0) + 10
        x2, y2 = pts.max(axis=0) - 10
        cv2.rectangle(img, (x1, y1), (x2, y2), col, -1, cv2.LINE_AA)
        cv2.rectangle(img, (x1 + 8, y1 + 30), (x2 - 8, y2 - 30), (30, 30, 30), -1)  # kính xe
    return img


class Stream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/snapshot"):
            ok, buf = cv2.imencode(".jpg", render())
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(buf.tobytes())
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                ok, buf = cv2.imencode(".jpg", render(), [cv2.IMWRITE_JPEG_QUALITY, 80])
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


# ---------------------------------------------------------------- hành vi xe
def send(msg):
    if not link.send(msg):
        print("  (chưa kết nối / chưa xác thực với server)")


def drive_to_slot(sid, delay=5.0):
    def go():
        time.sleep(delay)
        with lock:
            cars[sid] = random.choice(CAR_COLORS)
        print(f"  [xe] đã đỗ vào ô {SLOTS[sid].get('label', sid)}")
    threading.Thread(target=go, daemon=True).start()


def on_state(msg):
    global leds
    leds = msg["slots"]
    labels = [SLOTS[k].get("label", str(k)) for k in sorted(SLOTS)]
    print("  [LED]  " + " ".join(f"{lb}:{'ON ' if s == 'free' else ('blk' if s == 'reserved' else 'off')}"
                                for lb, s in zip(labels, leds)) + f"   (trống {msg['free']}/{msg['total']})")


def on_entry(msg):
    if msg is None:
        print("  [CỔNG VÀO] server không trả lời")
    elif msg["allowed"]:
        o = msg["oled"]
        print(f"  [OLED] {o['title']} | {' / '.join(o['lines'])} | mũi tên đầu: {o['arrow']}")
        print("  [RÀO VÀO] mở")
        drive_to_slot(msg["slot"])
    else:
        print(f"  [OLED] {msg['oled']['title']} — rào KHÔNG mở")


def on_command(msg):
    print(f"  [LỆNH] {msg['cmd']} {msg.get('gate', '')}")


def gate(name):
    """Xe tới cổng: gửi yêu cầu đã ký, chờ trả lời (ở luồng riêng để không chặn bàn phím)."""
    def go():
        res = link.request(name, 3)
        if name == "in":
            on_entry(res)
        elif res is not None:
            print("  [RÀO RA] mở")
    threading.Thread(target=go, daemon=True).start()


def read_secret(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def tls_fingerprint():
    import hashlib
    import ssl
    try:
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert((PC_DIR / "data" / "tls" / "server.crt").read_text())).hexdigest()
    except OSError:
        return None


def telemetry_thread():
    while True:
        time.sleep(2)
        if link.connected:
            send({"type": "telemetry", "data": {
                "dist_in_cm": round(random.uniform(80, 120), 1), "dist_out_cm": round(random.uniform(80, 120), 1),
                "barrier_in": "closed", "barrier_out": "closed", "cam_fps": 10.0, "cpu_temp": 48.5}})


def capture_reference():
    base = ARGS.api
    try:
        req = urllib.request.Request(f"{base}/api/auth/login", method="POST",
                                     data=json.dumps({"username": ARGS.user, "password": ARGS.password}).encode(),
                                     headers={"Content-Type": "application/json"})
        token = json.load(urllib.request.urlopen(req))["token"]
        req = urllib.request.Request(f"{base}/api/detector/reference", method="POST",
                                     headers={"Authorization": f"Bearer {token}"})
        urllib.request.urlopen(req)
        print("[mock-pi] đã chụp ảnh nền bãi trống")
    except Exception as e:
        print("[mock-pi] không tự chụp được ảnh nền (", e, ") — vào trang Thiết bị bấm 'Chụp ảnh nền'")


def slot_id(token):
    for sid, s in SLOTS.items():
        if token.upper() == s.get("label", "").upper() or token == str(sid):
            return sid
    print("  không có ô", token)
    return None


def car_in():
    gate("in")


def car_leave(sid):
    with lock:
        if sid not in cars:
            print(f"  ô {sid} đang trống")
            return
    def go():
        with lock:
            cars.pop(sid, None)
        time.sleep(3)
        gate("out")
    threading.Thread(target=go, daemon=True).start()


def auto_traffic():
    time.sleep(6)
    while True:
        time.sleep(random.uniform(3, 8))
        with lock:
            parked = list(cars)
        if parked and (random.random() < 0.4 or len(parked) >= len(SLOTS)):
            sid = random.choice(parked)
            print(f"[auto] xe rời ô {sid}")
            car_leave(sid)
        else:
            print("[auto] xe tới cổng vào")
            car_in()


def main():
    global ARGS, link
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="wss://localhost:8443", help="ws://localhost:8000 nếu chạy uvicorn không TLS")
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--key", default=None, help="mặc định đọc pc_server/data/pi.key")
    p.add_argument("--fingerprint", default=None, help="mặc định tính từ pc_server/data/tls/server.crt")
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin123")
    p.add_argument("--stream-port", type=int, default=8081)
    p.add_argument("--auto", action="store_true", help="xe tự ra vào ngẫu nhiên")
    p.add_argument("--no-reference", action="store_true")
    ARGS = p.parse_args()

    srv = ThreadingHTTPServer(("0.0.0.0", ARGS.stream_port), Stream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    key = ARGS.key or read_secret(PC_DIR / "data" / "pi.key")
    if not key:
        sys.exit("[mock-pi] chưa có khóa: chạy server một lần (tạo data/pi.key) hoặc truyền --key")
    link = PiLink(ARGS.server, key, 3, fingerprint=ARGS.fingerprint or tls_fingerprint(), device="mock-pi")
    link.hello = {"type": "hello", "device": "mock-pi", "version": "sim", "barrier": "servo",
                  "stream_port": ARGS.stream_port}
    link.on_state, link.on_command = on_state, on_command
    link.start()
    threading.Thread(target=telemetry_thread, daemon=True).start()
    print(f"[mock-pi] camera giả: http://localhost:{ARGS.stream_port}/stream.mjpg")
    if not ARGS.no_reference:
        for _ in range(200):
            if link.connected:
                break
            time.sleep(0.1)
        time.sleep(3)  # chờ server nhận khung hình đầu tiên
        capture_reference()
    if ARGS.auto:
        threading.Thread(target=auto_traffic, daemon=True).start()
    print(__doc__.split("Lệnh:")[1].strip() if "Lệnh:" in __doc__ else "")
    while True:
        try:
            line = input("> ").strip().split()
        except (EOFError, KeyboardInterrupt):
            if ARGS.auto:  # chạy nền không có stdin
                while True:
                    time.sleep(3600)
            break
        if not line:
            continue
        cmd = line[0].lower()
        if cmd == "in":
            car_in()
        elif cmd == "out":
            gate("out")
        elif cmd == "park" and len(line) > 1 and slot_id(line[1]):
            with lock:
                cars[slot_id(line[1])] = random.choice(CAR_COLORS)
        elif cmd == "leave" and len(line) > 1 and slot_id(line[1]):
            car_leave(slot_id(line[1]))
        elif cmd == "fill":
            with lock:
                for sid in SLOTS:
                    cars[sid] = random.choice(CAR_COLORS)
        elif cmd == "clear":
            with lock:
                cars.clear()
        elif cmd == "status":
            print("  có xe ở ô:", [SLOTS[k].get("label", k) for k in sorted(cars)])
        elif cmd in ("quit", "exit", "q"):
            break
        else:
            print("  lệnh không hợp lệ")


if __name__ == "__main__":
    main()
