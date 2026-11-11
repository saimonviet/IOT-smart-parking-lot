"""Kết nối WebSocket bảo mật tới pc_server, tự kết nối lại.

Bảo mật (xem secure_channel.py):
  - wss:// (TLS) + ghim vân tay chứng chỉ server (`fingerprint` trong config.yaml) -> chống nghe lén / server giả
  - bắt tay HMAC hai chiều bằng khóa bí mật `key` (khóa không bao giờ gửi qua mạng)
  - mọi tin hai chiều đều được ký, có số thứ tự + thời gian -> chống sửa tin, phát lại
"""
import hashlib
import json
import queue
import ssl
import threading
import time

import websocket  # websocket-client

import secure_channel as sc


def _norm_fp(fp):
    return (fp or "").replace(":", "").replace(" ", "").lower() or None


class PiLink:
    def __init__(self, url, key, reconnect_s=3, fingerprint=None, device="raspberry-pi-3"):
        if not key or len(str(key)) < 16 or not str(key).isascii():
            raise ValueError("server.key trong config.yaml chưa đặt / quá ngắn — lấy khóa bằng "
                             "`python tools/pi_secret.py` trên máy chạy pc_server")
        self.url = f"{url.rstrip('/')}/ws/pi"
        self.key = str(key)
        self.device = device
        self.fingerprint = _norm_fp(fingerprint)
        self.reconnect_s = reconnect_s
        self.connected = False  # True chỉ khi đã xác thực xong
        self.hello = {}
        self.on_state = lambda msg: None
        self.on_layout = lambda msg: None
        self.on_command = lambda msg: None
        self._replies = {"in": queue.Queue(), "out": queue.Queue()}
        self._ws = None
        self._stop = False
        self._send_lock = threading.Lock()
        self._reset()
        if self.url.startswith("ws://"):
            print("[link] CẢNH BÁO: đang dùng ws:// (không mã hóa). Server chỉ nhận khi chạy trên cùng máy; "
                  "với Pi thật hãy dùng wss://")
        elif not self.fingerprint:
            print("[link] CẢNH BÁO: chưa đặt server.fingerprint — không kiểm tra được chứng chỉ server")

    def _reset(self):
        self.connected = False
        self.sess = None
        self._nonce = self._cnonce = None
        self._trusted = False

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop = True
        if self._ws:
            self._ws.close()

    def send(self, msg):
        with self._send_lock:  # ký + gửi tuần tự (nhiều luồng cùng gửi) để seq đúng thứ tự
            try:
                if self.connected and self.sess:
                    self._ws.send(json.dumps(self.sess.seal(msg)))
                    return True
            except Exception:
                pass
        return False

    def request(self, gate, timeout=3.0):
        """Báo xe tới cổng, chờ server trả lời. Trả về dict hoặc None nếu quá hạn / mất kết nối."""
        q = self._replies[gate]
        while not q.empty():
            q.get_nowait()
        # gửi kèm thời gian chờ để server biết còn bao lâu cho việc đọc biển số
        if not self.send({"type": "arrive", "gate": gate, "timeout": timeout}):
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        # Không dùng chuỗi CA: chứng chỉ server tự ký, ta tự so vân tay SHA-256 trong _on_open (certificate pinning)
        sslopt = {"cert_reqs": ssl.CERT_NONE, "check_hostname": False}
        while not self._stop:
            self._reset()
            self._ws = websocket.WebSocketApp(
                self.url, on_open=self._on_open, on_message=self._on_message,
                on_close=lambda *a: self._reset(), on_error=self._on_error)
            self._ws.run_forever(ping_interval=10, ping_timeout=5, sslopt=sslopt)
            self._reset()
            time.sleep(self.reconnect_s)

    def _on_open(self, ws):
        if self.url.startswith("wss://") and self.fingerprint:
            der = ws.sock.sock.getpeercert(binary_form=True)
            got = hashlib.sha256(der).hexdigest()
            if got != self.fingerprint:
                print(f"[link] TỪ CHỐI server: vân tay chứng chỉ không khớp ({got[:16]}...) — "
                      "có thể đang bị giả mạo (MITM). Kiểm tra server.fingerprint.")
                ws.close()
                return
        self._trusted = True  # chờ challenge từ server

    def _on_error(self, ws, err):
        print(f"[link] lỗi kết nối: {err!r}")
        self._reset()

    def _fail(self, ws, why):
        print(f"[link] {why} — ngắt kết nối")
        ws.close()

    def _handshake(self, ws, msg):
        t = msg.get("type") if isinstance(msg, dict) else None
        if t == "challenge" and self._nonce is None:
            if not sc.valid_nonce(msg.get("nonce")) or msg.get("v") != sc.VERSION:
                return self._fail(ws, "challenge không hợp lệ")
            self._nonce, self._cnonce = msg["nonce"], sc.new_nonce()
            self._offset_ms = int(float(msg.get("server_time", time.time())) * 1000 - time.time() * 1000)
            ws.send(json.dumps(sc.auth(self.key, self._nonce, self._cnonce, self.device)))
        elif t == "auth_ok" and self._nonce:
            if not sc.check_auth_ok(self.key, self._nonce, self._cnonce, self.device, msg):
                return self._fail(ws, "server KHÔNG chứng minh được khóa bí mật (có thể là server giả)")
            self.sess = sc.Session(sc.session_key(self.key, self._nonce, self._cnonce),
                                   send_dir="pi", recv_dir="srv", clock_offset_ms=self._offset_ms)
            self.connected = True
            print("[link] đã xác thực với server (HMAC hai chiều"
                  + (", TLS đã ghim chứng chỉ)" if self.fingerprint and self.url.startswith("wss") else ")"))
            self.send(self.hello)
        else:
            self._fail(ws, f"tin không mong đợi khi bắt tay: {t}")

    def _on_message(self, ws, raw):
        if not self._trusted:
            return
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if self.sess is None:
            return self._handshake(ws, msg)
        try:
            msg = self.sess.open(msg)
        except sc.SecurityError as e:
            return self._fail(ws, f"tin từ server bị từ chối: {e}")
        t = msg.get("type")
        if t == "state":
            self.on_state(msg)
        elif t == "layout":
            self.on_layout(msg)
        elif t == "entry_result":
            self._replies["in"].put(msg)
        elif t == "exit_result":
            self._replies["out"].put(msg)
        elif t == "command":
            self.on_command(msg)
