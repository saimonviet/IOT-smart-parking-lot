"""Cấu hình server. Mọi giá trị đều có thể ghi đè bằng biến môi trường."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _env(name, default):
    return os.getenv(name, default)


DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "parking.db")))
LAYOUT_PATH = Path(_env("LAYOUT_PATH", str(BASE_DIR / "config" / "layout.json")))
REFERENCE_PATH = Path(_env("REFERENCE_PATH", str(DATA_DIR / "reference.jpg")))
WEB_DIST = BASE_DIR / "web" / "dist"

# --- Đăng nhập ---
ADMIN_USER = _env("ADMIN_USER", "admin")
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "admin123")
TOKEN_HOURS = int(_env("TOKEN_HOURS", "12"))


def _secret():
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    f = DATA_DIR / "secret.key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


SECRET_KEY = _secret()

# --- Kết nối với Raspberry Pi (bảo mật: TLS + xác thực HMAC, xem app/secure_channel.py) ---
def _pi_key():
    """Khóa bí mật dùng chung Pi <-> server. Mặc định sinh ngẫu nhiên vào data/pi.key (xem: python tools/pi_secret.py)."""
    if os.getenv("PI_KEY"):
        k = os.environ["PI_KEY"]
        if len(k) < 16 or k == "iot-parking":
            print("[security] CẢNH BÁO: PI_KEY quá ngắn / là giá trị mặc định — dễ bị đoán. "
                  "Bỏ biến PI_KEY để server tự sinh khóa ngẫu nhiên.")
        return k
    f = DATA_DIR / "pi.key"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(32))
    return f.read_text().strip()


PI_KEY = _pi_key()
PI_REQUIRE_TLS = _env("PI_REQUIRE_TLS", "1") == "1"   # Pi ngoài máy này bắt buộc dùng wss:// (TLS)
PI_AUTH_TIMEOUT = float(_env("PI_AUTH_TIMEOUT", "5"))  # giây chờ Pi trả lời challenge
PI_MAX_PENDING = 4                                     # số kết nối đang bắt tay cùng lúc tối đa

# --- Cổng chạy (python run.py) ---
HTTP_HOST = _env("HTTP_HOST", "127.0.0.1")  # HTTP thường: chỉ máy này (dashboard, mock Pi)
HTTP_PORT = int(_env("HTTP_PORT", "8000"))
TLS_HOST = _env("TLS_HOST", "0.0.0.0")      # HTTPS/WSS: cho Raspberry Pi và các máy khác trong LAN
TLS_PORT = int(_env("TLS_PORT", "8443"))
TLS_DIR = DATA_DIR / "tls"
TLS_CERT = Path(_env("TLS_CERT", str(TLS_DIR / "server.crt")))
TLS_KEY = Path(_env("TLS_KEY", str(TLS_DIR / "server.key")))
LED_COUNT = int(_env("LED_COUNT", "10"))  # số đèn LED ô đỗ trên Pi (raspberry_pi/config.yaml: leds.pins)

# --- Camera / nhận diện ---
# auto = lấy luồng MJPEG từ Pi khi Pi kết nối; hoặc URL, đường dẫn video/ảnh; none = tắt
VIDEO_SOURCE = _env("VIDEO_SOURCE", "auto")
DETECTOR = _env("DETECTOR", "yolo")  # classifier | yolo | background | none
CLASSIFIER_MODEL = Path(_env("CLASSIFIER_MODEL", str(BASE_DIR / "models" / "occupancy.pt")))
CLASSIFIER_META = CLASSIFIER_MODEL.with_suffix(".json")
YOLO_MODEL = _env("YOLO_MODEL", "yolov8n.pt")
# COCO: 2 car, 3 motorcycle, 5 bus, 7 truck. Rỗng = mọi lớp (hữu ích khi dùng xe mô hình / hộp đồ chơi)
YOLO_CLASSES = [int(x) for x in _env("YOLO_CLASSES", "2,3,5,7").split(",") if x.strip()]
YOLO_CONF = float(_env("YOLO_CONF", "0.25"))
YOLO_OVERLAP = float(_env("YOLO_OVERLAP", "0.25"))  # tỉ lệ ROI bị box xe phủ để coi là có xe
BG_THRESHOLD = int(_env("BG_THRESHOLD", "35"))      # độ lệch xám so với ảnh nền
BG_RATIO = float(_env("BG_RATIO", "0.20"))          # tỉ lệ điểm ảnh đổi trong ROI
DETECT_FPS = float(_env("DETECT_FPS", "3"))
CONFIRM_FRAMES = int(_env("CONFIRM_FRAMES", "3"))   # số khung liên tiếp để đổi trạng thái ô

# --- Nhận diện biển số (ESP32-CAM nhìn cả cổng vào và cổng ra, xem app/plates.py) ---
# URL/khóa ban đầu; sau đó chỉnh trên trang Thiết bị (lưu ở data/plate_cam.json)
PLATE_CAM_URL = _env("PLATE_CAM_URL", "")          # http://<ip-esp32>  | thư mục ảnh để chạy thử | rỗng = tắt
PLATE_CAM_KEY = _env("PLATE_CAM_KEY", "")          # khớp CAM_KEY trong firmware esp32_cam
PLATE_DET_MODEL = Path(_env("PLATE_DET_MODEL", str(BASE_DIR / "models" / "plate_det.pt")))
PLATE_OCR_MODEL = Path(_env("PLATE_OCR_MODEL", str(BASE_DIR / "models" / "plate_ocr.pt")))
PLATE_DET_CONF = float(_env("PLATE_DET_CONF", "0.35"))
PLATE_DET_IMGSZ = int(_env("PLATE_DET_IMGSZ", "640"))
PLATE_MIN_CONF = float(_env("PLATE_MIN_CONF", "0.5"))   # dưới ngưỡng này coi như KHÔNG đọc được
PLATE_MAX_FRAMES = int(_env("PLATE_MAX_FRAMES", "4"))   # số ảnh tối đa mỗi lượt (bỏ phiếu)
PLATE_BUDGET = float(_env("PLATE_BUDGET", "4.0"))       # giây tối đa để đọc biển (còn bị giới hạn theo timeout của Pi)
# 1 = bắt buộc đọc được biển mới cho vào/ra (đúng nghiệp vụ); 0 = không đọc được vẫn cho qua, chỉ ghi cảnh báo
PLATE_REQUIRED = _env("PLATE_REQUIRED", "1") == "1"
PLATE_MATCH_DIST = int(_env("PLATE_MATCH_DIST", "1"))  # cổng ra: chấp nhận lệch tối đa n ký tự so với lúc vào
PLATE_IMG_DIR = DATA_DIR / "plates"                     # ảnh bằng chứng mỗi lượt đọc

# --- Nghiệp vụ ---
RESERVE_TIMEOUT = int(_env("RESERVE_TIMEOUT", "90"))  # giây giữ chỗ cho xe vừa vào
RATE_PER_HOUR = int(_env("RATE_PER_HOUR", "5000"))    # VND / giờ, tính theo khối 15 phút
BLOCK_MINUTES = 15
