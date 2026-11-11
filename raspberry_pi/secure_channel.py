"""Giao thức bảo mật kênh Raspberry Pi <-> server (chỉ dùng thư viện chuẩn).

File này có HAI BẢN GIỐNG HỆT NHAU: pc_server/app/secure_channel.py và raspberry_pi/secure_channel.py.
Sửa bản nào thì chép đè sang bản kia.

1) Bắt tay (challenge-response, xác thực HAI CHIỀU). Khóa bí mật K không bao giờ đi trên đường truyền:
     server -> Pi : {"type":"challenge", "v":1, "nonce":Ns, "server_time":t}
     Pi -> server : {"type":"auth", "v":1, "device":D, "cnonce":Nc, "proof":HMAC(K, "pi-auth|1|Ns|Nc|D")}
     server -> Pi : {"type":"auth_ok", "proof":HMAC(K, "srv-auth|1|Ns|Nc|D")}
   Server kiểm tra proof của Pi (chặn Pi giả); Pi kiểm tra proof của server (chặn server giả).
   Khóa phiên Ks = HMAC(K, "session|1|Ns|Nc"): mỗi kết nối một khóa khác, tin của phiên cũ không dùng lại được.

2) Sau bắt tay, MỌI tin đều được bọc và ký:
     {"seq":n, "ts":t_ms, "body":{...}, "mac":HMAC(Ks, "<chiều>|n|t_ms|<body JSON chuẩn hóa>")}
   - mac sai             -> tin bị sửa trên đường truyền / bị giả mạo
   - seq không tăng      -> tin bị phát lại (replay)
   - ts lệch quá 30 giây -> tin cũ bị giữ lại rồi gửi
   "<chiều>" là "pi" hoặc "srv" nên tin của chiều này không thể dội ngược lại cho chiều kia.
"""
import hashlib
import hmac
import json
import os
import re
import time

VERSION = 1
MAX_SKEW_MS = 30_000
_NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class SecurityError(Exception):
    """Tin nhận được không qua được kiểm tra bảo mật."""


def _k(key):
    return key.encode() if isinstance(key, str) else key


def _mac(key, *parts):
    return hmac.new(_k(key), "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()


def new_nonce():
    return os.urandom(16).hex()


def valid_nonce(n):
    return isinstance(n, str) and bool(_NONCE_RE.match(n))


def valid_device(d):
    return isinstance(d, str) and bool(_DEVICE_RE.match(d))


def canon(body):
    """JSON chuẩn hóa (khóa sắp xếp, không khoảng trắng) để hai bên tính MAC trên cùng một chuỗi."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def session_key(key, nonce, cnonce):
    return hmac.new(_k(key), f"session|{VERSION}|{nonce}|{cnonce}".encode(), hashlib.sha256).digest()


# ---------------------------------------------------------------- phía server
def challenge(nonce):
    return {"type": "challenge", "v": VERSION, "nonce": nonce, "server_time": time.time()}


def check_auth(key, nonce, msg):
    """Kiểm tra tin "auth" của Pi. Đúng -> trả tên thiết bị, sai -> None."""
    if not isinstance(msg, dict) or msg.get("type") != "auth" or msg.get("v") != VERSION:
        return None
    device, cnonce, proof = msg.get("device"), msg.get("cnonce"), msg.get("proof")
    if not (valid_device(device) and valid_nonce(cnonce) and isinstance(proof, str)) or cnonce == nonce:
        return None
    if hmac.compare_digest(_mac(key, "pi-auth", VERSION, nonce, cnonce, device), proof):
        return device
    return None


def auth_ok(key, nonce, cnonce, device):
    return {"type": "auth_ok", "proof": _mac(key, "srv-auth", VERSION, nonce, cnonce, device)}


# ---------------------------------------------------------------- phía Pi
def auth(key, nonce, cnonce, device):
    return {"type": "auth", "v": VERSION, "device": device, "cnonce": cnonce,
            "proof": _mac(key, "pi-auth", VERSION, nonce, cnonce, device)}


def check_auth_ok(key, nonce, cnonce, device, msg):
    return (isinstance(msg, dict) and msg.get("type") == "auth_ok" and isinstance(msg.get("proof"), str)
            and hmac.compare_digest(_mac(key, "srv-auth", VERSION, nonce, cnonce, device), msg["proof"]))


# ---------------------------------------------------------------- tin đã ký trong một phiên
class Session:
    def __init__(self, key, send_dir, recv_dir, clock_offset_ms=0):
        self.key, self.send_dir, self.recv_dir = key, send_dir, recv_dir
        self.offset = int(clock_offset_ms)
        self.tx = 0  # seq của tin gửi gần nhất
        self.rx = 0  # seq của tin nhận hợp lệ gần nhất

    def now_ms(self):
        return int(time.time() * 1000) + self.offset

    def seal(self, body):
        """Ký một tin để gửi. Gọi tuần tự (giữ khóa) để seq ra đúng thứ tự gửi."""
        self.tx += 1
        ts = self.now_ms()
        return {"seq": self.tx, "ts": ts, "body": body,
                "mac": _mac(self.key, self.send_dir, self.tx, ts, canon(body))}

    def open(self, msg):
        """Kiểm tra một tin nhận được; hợp lệ -> trả body, không -> SecurityError."""
        if not isinstance(msg, dict):
            raise SecurityError("gói tin không đúng định dạng")
        seq, ts, body, mac = msg.get("seq"), msg.get("ts"), msg.get("body"), msg.get("mac")
        if not (type(seq) is int and type(ts) is int and isinstance(body, dict) and isinstance(mac, str)):
            raise SecurityError("gói tin không được ký")
        if not hmac.compare_digest(_mac(self.key, self.recv_dir, seq, ts, canon(body)), mac):
            raise SecurityError("sai chữ ký MAC (gói tin bị sửa hoặc giả mạo)")
        if seq <= self.rx:
            raise SecurityError(f"gói tin bị phát lại (seq {seq} đã nhận trước đó)")
        if abs(ts - self.now_ms()) > MAX_SKEW_MS:
            raise SecurityError("gói tin quá cũ (lệch thời gian quá 30 giây)")
        self.rx = seq
        return body
