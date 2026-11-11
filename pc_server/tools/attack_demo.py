"""Demo các kiểu tấn công vào kênh Raspberry Pi <-> server và kết quả bị chặn.

Chạy (từ thư mục pc_server, khi server đang chạy bằng `python run.py`):
    python tools/attack_demo.py                 # các kịch bản 1-6
    python tools/attack_demo.py --bruteforce    # thêm kịch bản 7: dò khóa -> IP bị chặn 5 phút
                                                #   (chặn cả Pi giả chạy trên máy này trong 5 phút!)
Kịch bản 3-5 dùng khóa thật để giả lập kẻ tấn công đứng giữa SỬA / PHÁT LẠI gói tin hợp lệ;
chúng tạm thay chỗ Pi đang kết nối (Pi sẽ tự kết nối lại sau vài giây).
"""
import argparse
import json
import ssl
import sys
import threading
import time
from pathlib import Path

import websocket  # websocket-client

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE.parent / "raspberry_pi"))
from app import secure_channel as sc  # noqa: E402

SSLOPT = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
results = []


def connect(url, path="/ws/pi"):
    return websocket.create_connection(url + path, sslopt=SSLOPT, timeout=8)


def recv(ws):
    """('msg', dict) | ('closed', mã đóng) | ('closed', None)."""
    try:
        while True:
            op, data = ws.recv_data(control_frame=True)
            if op == websocket.ABNF.OPCODE_CLOSE:
                return "closed", int.from_bytes(data[:2], "big") if len(data) >= 2 else None
            if op == websocket.ABNF.OPCODE_TEXT:
                return "msg", json.loads(data)
    except Exception:
        return "closed", None


def login(url, key, device="attack-demo"):
    """Bắt tay đúng giao thức. Trả về (ws, session) hoặc (ws, None) nếu bị từ chối."""
    ws = connect(url)
    kind, ch = recv(ws)
    if kind != "msg" or ch.get("type") != "challenge":
        return ws, None
    cn = sc.new_nonce()
    ws.send(json.dumps(sc.auth(key, ch["nonce"], cn, device)))
    kind, ok = recv(ws)
    if kind != "msg" or not sc.check_auth_ok(key, ch["nonce"], cn, device, ok):
        return ws, None
    off = int(ch["server_time"] * 1000 - time.time() * 1000)
    return ws, sc.Session(sc.session_key(key, ch["nonce"], cn), "pi", "srv", off)


def report(n, title, blocked, detail):
    results.append(blocked)
    print(f"[{n}] {title}\n    -> {'BỊ CHẶN ✔' if blocked else 'KHÔNG bị chặn ✘'}  ({detail})\n")


def drain_until_closed(ws, seconds=3):
    end = time.time() + seconds
    while time.time() < end:
        kind, v = recv(ws)
        if kind == "closed":
            return v
    return "vẫn mở"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="wss://localhost:8443")
    ap.add_argument("--bruteforce", action="store_true")
    a = ap.parse_args()
    key = (BASE / "data" / "pi.key").read_text().strip()

    # 1. kiểu kết nối cũ: khóa mặc định trên URL, gửi lệnh không ký
    ws = connect(a.url, "/ws/pi?key=iot-parking")
    recv(ws)  # challenge
    ws.send(json.dumps({"type": "hello", "device": "fake"}))
    ws.send(json.dumps({"type": "arrive", "gate": "in"}))
    kind, v = recv(ws)
    report(1, "Pi giả dùng khóa mặc định 'iot-parking' trên URL (giao thức cũ)",
           kind == "closed", f"server đóng kết nối, mã {v}")

    # 2. bắt tay đúng giao thức nhưng đoán sai khóa
    ws, sess = login(a.url, "doan-sai-khoa-1234567890")
    report(2, "Kẻ tấn công bắt tay đúng giao thức nhưng SAI khóa", sess is None, "không nhận được auth_ok")

    # 3. sửa gói tin hợp lệ trên đường truyền
    ws, sess = login(a.url, key)
    msg = sess.seal({"type": "arrive", "gate": "out"})
    msg["body"]["gate"] = "in"  # kẻ đứng giữa sửa cổng ra -> cổng vào
    ws.send(json.dumps(msg))
    code = drain_until_closed(ws)
    report(3, "Sửa nội dung gói tin đã ký (gate out -> in)", code == 4400, f"server đóng kết nối, mã {code}")

    # 4. phát lại cùng một gói tin
    ws, sess = login(a.url, key)
    msg = sess.seal({"type": "telemetry", "data": {"demo": 1}})
    ws.send(json.dumps(msg))
    ws.send(json.dumps(msg))  # gửi lại y hệt
    code = drain_until_closed(ws)
    report(4, "Phát lại (replay) một gói tin hợp lệ trong cùng phiên", code == 4400, f"mã {code}")

    # 5. phát lại gói tin của phiên cũ sang phiên mới
    ws, sess = login(a.url, key)
    old = sess.seal({"type": "arrive", "gate": "out"})
    ws.close()
    ws, sess = login(a.url, key)
    ws.send(json.dumps(old))
    code = drain_until_closed(ws)
    report(5, "Phát lại gói tin của phiên trước sang kết nối mới", code == 4400, f"mã {code} (khóa phiên khác)")

    # 6. server giả: Pi không chịu xác thực với server không có khóa
    from websockets.sync.server import serve
    from link import PiLink

    def fake_server(conn):
        conn.send(json.dumps(sc.challenge(sc.new_nonce())))
        conn.recv()  # Pi gửi proof (không lộ khóa)
        conn.send(json.dumps({"type": "auth_ok", "proof": "0" * 64}))
        conn.send(json.dumps({"type": "command", "cmd": "open_barrier", "gate": "in"}))
        time.sleep(1)

    opened = []
    with serve(fake_server, "127.0.0.1", 0) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.socket.getsockname()[1]
        link = PiLink(f"ws://127.0.0.1:{port}", key, reconnect_s=60, device="victim-pi")
        link.on_command = opened.append
        link.start()
        time.sleep(2)
        link.stop()
        srv.shutdown()
    report(6, "Server giả gửi lệnh mở rào cho Pi", not link.connected and not opened,
           "Pi phát hiện server không chứng minh được khóa, bỏ qua lệnh")

    # 7. dò khóa
    if a.bruteforce:
        refused_at = None
        for i in range(1, 8):
            try:
                ws, sess = login(a.url, f"thu-khoa-sai-{i:02d}-xxxxxxxx")
            except Exception:
                refused_at = i
                break
        report(7, "Dò khóa liên tục (brute force)", refused_at is not None,
               f"bị từ chối ngay từ lần thử {refused_at}" if refused_at else "chưa bị chặn")

    print(f"Kết quả: {sum(results)}/{len(results)} kiểu tấn công bị chặn. Xem nhật ký trên dashboard (mục sự kiện 'security').")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
