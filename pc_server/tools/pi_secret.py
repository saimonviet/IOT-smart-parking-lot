"""In ra đoạn cấu hình `server:` để dán vào raspberry_pi/config.yaml (khóa bí mật + vân tay chứng chỉ TLS).
Chạy (từ thư mục pc_server):  python tools/pi_secret.py
GIỮ BÍ MẬT khóa này: ai có nó có thể giả làm Raspberry Pi. Muốn đổi khóa: xóa data/pi.key, chạy lại server và script này.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, tls  # noqa: E402

if tls.ensure_cert():
    print(f"(đã tạo chứng chỉ mới: {config.TLS_CERT})")
ips = [ip for ip in tls.local_ips() if not ip.startswith("127.")]
ip = ips[0] if ips else "<ip-máy-tính>"
print(f"""# Dán vào raspberry_pi/config.yaml (thay mục server cũ). IP máy này: {', '.join(ips) or '?'}
server:
  url: wss://{ip}:{config.TLS_PORT}
  key: "{config.PI_KEY}"
  fingerprint: "{tls.fingerprint()}"
  reconnect_s: 3
  request_timeout_s: 3""")
