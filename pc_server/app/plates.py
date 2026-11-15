"""Nhận diện biển số xe (ALPR) bằng một ESP32-CAM nhìn cả cổng vào và cổng ra.

Luồng xử lý khi Pi báo "có xe ở cổng":
  1. Chụp vài ảnh JPEG từ ESP32-CAM (http://<ip>/capture) trong khoảng thời gian cho phép.
  2. Cắt vùng ảnh của cổng đó (ROI cổng vào / cổng ra trong data/plate_cam.json) — một camera nhìn cả hai làn.
  3. Phát hiện biển số (YOLO, models/plate_det.pt) -> cắt biển -> đọc ký tự (CRNN-CTC, models/plate_ocr.pt).
  4. Chuẩn hóa theo định dạng biển Việt Nam, bỏ phiếu giữa các ảnh, lưu ảnh làm bằng chứng.

Mô hình huấn luyện trong D:/model_training (xem train_plate.ipynb), xuất ra pc_server/models/.
"""
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import config

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp"}

# ============================================================ định dạng biển số Việt Nam
# Biển ô tô:  51G-123.45 | 51G-1234 | 30LD-123.45     Biển xe máy: 59-X1 234.56 | 29-AB 123.45
# Dạng chuẩn hóa (không dấu): 2 số tỉnh + sê-ri (1–2 chữ, hoặc chữ + số) + 4–5 số.
PLATE_RE = re.compile(r"^(\d{2})([A-Z]{1,2}|[A-Z]\d)(\d{4,5})$")
TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "U": "0", "I": "1", "L": "1", "J": "1", "Z": "2", "B": "8",
            "S": "5", "G": "6", "T": "7", "A": "4"}
TO_LETTER = {"0": "D", "8": "B", "5": "S", "6": "G", "2": "Z", "1": "T", "4": "A", "7": "T"}


def clean(text):
    return re.sub(r"[^0-9A-Z]", "", (text or "").upper())


def fix_plate(text):
    """Sửa nhầm lẫn chữ/số theo vị trí (2 ký tự đầu là số, ký tự thứ 3 là chữ, cuối là số)."""
    t = list(clean(text))
    if len(t) < 7:
        return "".join(t)
    for i in (0, 1):
        t[i] = TO_DIGIT.get(t[i], t[i])
    t[2] = TO_LETTER.get(t[2], t[2])
    # 4 ký tự cuối luôn là số; biển 9 ký tự (sê-ri 2 ký tự + 5 số) thì ký tự thứ 5 cũng là số.
    # Ký tự thứ 4 của biển 8 ký tự còn mơ hồ (51G-123.45 hay 30LD-1234) nên giữ nguyên.
    tail = 5 if len(t) == 9 else 4
    for i in range(max(3, len(t) - tail), len(t)):
        t[i] = TO_DIGIT.get(t[i], t[i])
    return "".join(t)


def is_valid(plate):
    return bool(PLATE_RE.match(plate or ""))


def pretty(plate):
    """51G12345 -> 51G-123.45 ; 59X123456 -> 59-X1 234.56 ; 51G1234 -> 51G-1234."""
    m = PLATE_RE.match(plate or "")
    if not m:
        return plate or ""
    prov, series, num = m.groups()
    num_s = f"{num[:3]}.{num[3:]}" if len(num) == 5 else num
    if len(series) == 2 and series[1].isdigit():  # sê-ri xe máy (X1, B2...)
        return f"{prov}-{series} {num_s}"
    return f"{prov}{series}-{num_s}"


def distance(a, b):
    """Khoảng cách Levenshtein (để so khớp biển lúc ra với lúc vào khi OCR sai 1 ký tự)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ============================================================ cấu hình camera biển số
CAM_PATH = config.DATA_DIR / "plate_cam.json"
DEFAULT_CAM = {
    "url": config.PLATE_CAM_URL,   # http://<ip-esp32>  | thư mục/ảnh để chạy thử | "" = tắt
    "key": config.PLATE_CAM_KEY,   # khóa truy cập ESP32-CAM (?key=...), khớp CAM_KEY trong firmware
    # vùng ảnh (tỉ lệ 0–1: x1, y1, x2, y2) của từng làn. Mặc định cả khung hình: Pi xoay camera (servo) về đúng cổng.
    # Camera cố định nhìn cả hai làn thì chia đôi, vd. in [0, 0, 0.5, 1] và out [0.5, 0, 1, 1].
    "roi": {"in": [0.0, 0.0, 1.0, 1.0], "out": [0.0, 0.0, 1.0, 1.0]},
    "flash": 80,                   # đèn flash ESP32-CAM bật khi chụp biển (0 = tắt, 1–255; lóa biển thì giảm)
    "aim": False,                  # True: ESP32 có động cơ bước xoay camera -> gọi /aim?gate=in|out trước khi chụp
}


def load_cam():
    cfg = json.loads(json.dumps(DEFAULT_CAM))
    try:
        saved = json.loads(CAM_PATH.read_text(encoding="utf-8"))
        cfg.update({k: v for k, v in saved.items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def save_cam(cfg):
    CAM_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================ nguồn ảnh
class PlateCamera:
    """Lấy ảnh theo yêu cầu từ ESP32-CAM (không giữ luồng MJPEG liên tục -> ESP32 mát và ổn định hơn)."""

    def __init__(self):
        self.cfg = load_cam()
        self.lock = threading.Lock()
        self.last_ok = 0.0
        self.error = ""
        self.last_frame = None
        self._files, self._fi = [], 0

    def configure(self, cfg):
        self.cfg = cfg
        self.error = ""
        self._files = []

    def online(self):
        return time.time() - self.last_ok < 30

    def grab(self, timeout=1.5):
        url = (self.cfg.get("url") or "").strip()
        if not url:
            self.error = "chưa cấu hình camera biển số"
            return None
        try:
            with self.lock:
                img = self._grab_file(url) if not url.startswith("http") else self._grab_http(url, timeout)
            if img is None:
                raise RuntimeError("ảnh rỗng / không giải mã được")
            self.last_ok, self.error, self.last_frame = time.time(), "", img
            return img
        except Exception as e:
            self.error = f"{e}"
            return None

    def _grab_http(self, url, timeout):
        base = url.rstrip("/")
        path = "" if base.endswith((".jpg", ".jpeg")) or "/capture" in base else "/capture"
        q = {"_": str(int(time.time() * 1000))}
        if self.cfg.get("key"):
            q["key"] = self.cfg["key"]
        full = f"{base}{path}{'&' if '?' in base else '?'}{urllib.parse.urlencode(q)}"
        with urllib.request.urlopen(full, timeout=timeout) as r:
            data = r.read()
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    def set_flash(self, level):
        """Bật/tắt đèn flash GPIO4 của ESP32-CAM (/control?flash=0..255). Lỗi thì bỏ qua — chỉ là hỗ trợ ánh sáng."""
        url = (self.cfg.get("url") or "").strip()
        if not url.startswith("http"):
            return False
        q = {"flash": int(max(0, min(255, level)))}
        if self.cfg.get("key"):
            q["key"] = self.cfg["key"]
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/control?{urllib.parse.urlencode(q)}", timeout=1.0) as r:
                r.read()
            return True
        except Exception:
            return False

    def aim(self, gate, timeout=8.0):
        """Bảo ESP32 quay động cơ bước về cổng `gate` (trả lời sau khi quay xong + chờ hết rung). None nếu lỗi."""
        url = (self.cfg.get("url") or "").strip()
        if not url.startswith("http"):
            return {"moved": 0, "ms": 0}   # nguồn ảnh/thư mục chạy thử: không có động cơ
        q = {"gate": gate}
        if self.cfg.get("key"):
            q["key"] = self.cfg["key"]
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/aim?{urllib.parse.urlencode(q)}", timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except Exception as e:
            self.error = f"không xoay được camera: {e}"
            return None

    def _grab_file(self, path):
        """Chạy thử không cần ESP32: một ảnh, hoặc thư mục ảnh (lần lượt từng ảnh mỗi lần xe tới)."""
        p = Path(path)
        if p.is_dir():
            if not self._files:
                self._files = sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT)
            if not self._files:
                raise RuntimeError("thư mục không có ảnh")
            f = self._files[self._fi % len(self._files)]
            return cv2.imread(str(f))
        if not p.exists():
            raise RuntimeError(f"không thấy {path}")
        return cv2.imread(str(p))

    def next_file(self):
        """Sang ảnh tiếp theo (chế độ thư mục) sau mỗi lượt đọc."""
        self._fi += 1


# ============================================================ mô hình
def _crop_roi(img, roi):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = roi or (0, 0, 1, 1)
    a, b = int(max(0, min(x1, x2)) * w), int(max(0, min(y1, y2)) * h)
    c, d = int(min(1, max(x1, x2)) * w), int(min(1, max(y1, y2)) * h)
    if c - a < 16 or d - b < 16:
        return img, (0, 0)
    return img[b:d, a:c], (a, b)


def ocr_input(crop, meta, two_rows=None):
    """Tiền xử lý ảnh biển cho OCR — GIỐNG HỆT hàm cùng tên trong model_training/plate_lib.py.

    Biển 2 dòng: cắt đôi theo chiều cao rồi ghép ngang thành 1 dòng, nhờ vậy một mô hình CRNN đọc được
    cả biển dài lẫn biển vuông. two_rows lấy từ lớp YOLO (plate_1row / plate_2row); None = đoán theo tỉ lệ.
    """
    H, W = meta["img_h"], meta["img_w"]
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = g.shape[:2]
    if two_rows is None:
        two_rows = w / max(h, 1) < meta.get("split_ratio", 2.2)
    if two_rows:
        ov = int(h * 0.04)
        top, bot = g[: h // 2 + ov], g[h // 2 - ov:]
        g = np.hstack([cv2.resize(top, (W // 2, H)), cv2.resize(bot, (W // 2, H))])
    else:
        g = cv2.resize(g, (W, H))
    x = g.astype(np.float32) / 255.0
    return (x - meta.get("mean", 0.5)) / meta.get("std", 0.5)


class PlateModel:
    """YOLO phát hiện biển + CRNN-CTC đọc ký tự. Thiếu mô hình thì báo lỗi rõ ràng, không làm hỏng server."""

    def __init__(self):
        self.det = self.ocr = self.meta = None
        self.error = ""
        self.lock = threading.Lock()
        try:
            import torch
            self.torch = torch
            if not config.PLATE_DET_MODEL.exists():
                raise FileNotFoundError(f"chưa có {config.PLATE_DET_MODEL.name} (huấn luyện trong model_training)")
            if not config.PLATE_OCR_MODEL.exists():
                raise FileNotFoundError(f"chưa có {config.PLATE_OCR_MODEL.name} (huấn luyện trong model_training)")
            from ultralytics import YOLO
            self.det = YOLO(str(config.PLATE_DET_MODEL))
            self.meta = json.loads(config.PLATE_OCR_MODEL.with_suffix(".json").read_text(encoding="utf-8"))
            self.ocr = torch.jit.load(str(config.PLATE_OCR_MODEL), map_location="cpu").eval()
            self.alphabet = self.meta["alphabet"]  # chỉ số 0 = blank của CTC
        except Exception as e:
            self.error = f"Mô hình biển số: {e}"
            print("[plate]", self.error)
            return
        # chạy nháp 1 lần: lần suy luận đầu chậm (~2 s: khởi tạo YOLO/torch), không để xe đầu tiên phải chờ
        try:
            t = time.time()
            self.recognize(np.zeros((480, 640, 3), np.uint8))
            print(f"[plate] mô hình sẵn sàng (khởi động nóng {time.time() - t:.1f}s)")
        except Exception as e:
            print("[plate] khởi động nóng lỗi (bỏ qua):", e)

    @property
    def ready(self):
        return self.det is not None and self.ocr is not None

    def detect(self, img):
        r = self.det.predict(img, conf=config.PLATE_DET_CONF, imgsz=config.PLATE_DET_IMGSZ, verbose=False)[0]
        names = r.names or {}
        out = []
        for b in r.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            name = str(names.get(int(b.cls[0]), ""))
            two = True if "2" in name else False if "1" in name else None  # mô hình 1 lớp -> đoán theo tỉ lệ
            out.append(([x1, y1, x2, y2], float(b.conf[0]), two))
        return out

    def read(self, crops, rows=None):
        if not crops:
            return []
        rows = rows or [None] * len(crops)
        x = np.stack([ocr_input(c, self.meta, r) for c, r in zip(crops, rows)])[:, None]
        with self.torch.no_grad():
            logits = self.ocr(self.torch.from_numpy(x))           # (N, T, C)
            prob = logits.softmax(-1).numpy()
        res = []
        for p in prob:
            idx, conf = p.argmax(-1), p.max(-1)
            chars, confs, prev = [], [], 0
            for i, c in zip(idx, conf):
                if i != prev and i != 0:
                    chars.append(self.alphabet[i - 1])
                    confs.append(c)
                prev = i
            res.append(("".join(chars), float(np.min(confs)) if confs else 0.0))
        return res

    def recognize(self, img):
        """Trả về [(biển_chuẩn_hóa, độ_tin_cậy, box)] theo thứ tự box lớn (xe gần) trước."""
        with self.lock:
            boxes = self.detect(img)
            h, w = img.shape[:2]
            crops = []
            for (x1, y1, x2, y2), _, _ in boxes:
                px, py = (x2 - x1) * 0.06, (y2 - y1) * 0.10
                a, b = int(max(0, x1 - px)), int(max(0, y1 - py))
                c, d = int(min(w, x2 + px)), int(min(h, y2 + py))
                crops.append(img[b:d, a:c])
            texts = self.read(crops, [b[2] for b in boxes])
        out = []
        for ((box, dconf, _), (text, oconf)) in zip(boxes, texts):
            plate = fix_plate(text)
            out.append((plate, dconf * oconf, box))
        out.sort(key=lambda r: -(r[2][2] - r[2][0]) * (r[2][3] - r[2][1]))
        return out


# ============================================================ xếp lượt dùng camera (1 camera cho 2 cổng)
class CameraQueue:
    """Mỗi lúc chỉ một cổng dùng camera. Cổng RA được ưu tiên: khi camera xoay được (aim), yêu cầu của cổng VÀO
    chờ một khoảng ngắn để nếu cổng ra cũng vừa có xe thì cổng ra được quét trước; xe vào chỉ được phục vụ khi
    không còn xe ra nào chờ. Một lượt đang đọc dở thì không bị ngắt."""

    PRIORITY = ("out", "in")

    def __init__(self, window_s=0.3):
        self.window = window_s
        self.cv = threading.Condition()
        self.owner = None
        self.waiting = {}

    def _turn(self, gate, use_window):
        if self.owner is not None:
            return False
        for g in self.PRIORITY:
            if g == gate:
                break
            if g in self.waiting:
                return False
        if use_window and gate != self.PRIORITY[0]:
            return time.time() - self.waiting[gate] >= self.window
        return True

    def acquire(self, gate, timeout, use_window=True):
        t0 = time.time()
        with self.cv:
            self.waiting[gate] = t0
            try:
                while not self._turn(gate, use_window):
                    left = timeout - (time.time() - t0)
                    if left <= 0:
                        return False
                    self.cv.wait(min(0.05, left))
                self.owner = gate
                return True
            finally:
                self.waiting.pop(gate, None)

    def release(self, gate):
        with self.cv:
            if self.owner == gate:
                self.owner = None
            self.cv.notify_all()


# ============================================================ đọc biển số tại cổng
class PlateReader:
    def __init__(self):
        self.cam = PlateCamera()
        self.model = None
        self.recent = []  # vài lần đọc gần nhất (hiện trên trang Thiết bị)
        self._load_lock = threading.Lock()
        self.queue = CameraQueue()

    def ensure_model(self):
        with self._load_lock:
            if self.model is None:
                self.model = PlateModel()
            return self.model

    def reload_model(self):
        with self._load_lock:
            self.model = None
        return self.ensure_model()

    @property
    def enabled(self):
        return bool((self.cam.cfg.get("url") or "").strip())

    def status(self):
        m = self.model
        return {"enabled": self.enabled, "url": self.cam.cfg.get("url"), "online": self.cam.online(),
                "error": self.cam.error, "model_ready": bool(m and m.ready),
                "model_error": m.error if m else "", "roi": self.cam.cfg.get("roi"),
                "required": config.PLATE_REQUIRED, "recent": self.recent[:8]}

    FLASH_WARMUP_S = 0.25   # chờ cảm biến ảnh chỉnh lại độ phơi sáng sau khi bật flash

    def read(self, gate, budget=None):
        """Đọc biển số ở một cổng. `budget` = tổng số giây được phép (gồm chờ lượt + xoay camera + chụp + nhận diện).

        Trả về dict: plate (chuẩn hóa hoặc None), display, conf, valid, image (đường dẫn ảnh bằng chứng), reason,
        timing {wait_ms, aim_ms, frames, capture_ms, detect_ms, read_ms} để biết chậm ở bước nào.
        """
        t0 = time.time()
        aim = bool(self.cam.cfg.get("aim")) and self.enabled
        budget = budget or (config.PLATE_BUDGET + (config.PLATE_AIM_MAX_S if aim else 0))
        t = {"wait_ms": 0, "aim_ms": 0, "frames": 0, "capture_ms": 0, "detect_ms": 0, "flash": False}
        if not self.queue.acquire(gate, timeout=max(0.5, budget - 1.0), use_window=aim):
            res = self._done(gate, None, 0.0, None, "Camera đang bận với cổng kia quá lâu")
            res["timing"] = {**t, "wait_ms": int((time.time() - t0) * 1000), "read_ms": int((time.time() - t0) * 1000)}
            return res
        try:
            t["wait_ms"] = int((time.time() - t0) * 1000)
            self._t = t
            if aim:
                ta = time.time()
                r = self.cam.aim(gate, timeout=config.PLATE_AIM_MAX_S)
                t["aim_ms"] = int((time.time() - ta) * 1000)
                if r is None:
                    res = self._done(gate, None, 0.0, None, f"Không xoay được camera về cổng: {self.cam.error}")
                    res["timing"] = {**t, "read_ms": int((time.time() - t0) * 1000)}
                    return res
            flash = int(self.cam.cfg.get("flash") or 0)
            if flash > 0 and self.enabled:
                t["flash"] = self.cam.set_flash(flash)
                if t["flash"]:
                    time.sleep(self.FLASH_WARMUP_S)
            try:
                # phần còn lại cho chụp + nhận diện (tối đa PLATE_BUDGET)
                left = min(config.PLATE_BUDGET, budget - (time.time() - t0))
                res = self._read(gate, max(0.8, left), time.time())
            finally:
                if t["flash"]:
                    self.cam.set_flash(0)
            res["timing"] = {**t, "read_ms": int((time.time() - t0) * 1000)}
            return res
        finally:
            self.queue.release(gate)

    def _read(self, gate, budget, t0):
        model = self.ensure_model()
        if not self.enabled:
            return self._done(gate, None, 0.0, None, "Chưa cấu hình camera biển số")
        if not model.ready:
            return self._done(gate, None, 0.0, None, model.error)
        roi = (self.cam.cfg.get("roi") or {}).get(gate)
        # 1) CHỤP: lấy liền PLATE_FRAMES ảnh từ ESP32 (xe đang đứng yên ở cổng) — dành ~30% thời gian cho bước nhận diện
        shots = []
        tc = time.time()
        while len(shots) < config.PLATE_FRAMES:
            left = budget - (time.time() - t0)
            if shots and left < budget * 0.3:
                break
            img = self.cam.grab(timeout=max(0.3, left * 0.7))
            if img is None:
                break
            shots.append(img)
            if len(shots) < config.PLATE_FRAMES and config.PLATE_FRAME_GAP_S > 0:
                time.sleep(config.PLATE_FRAME_GAP_S)
        self._t["capture_ms"] = int((time.time() - tc) * 1000)
        self._t["frames"] = frames = len(shots)
        if self.cam.cfg.get("url") and not str(self.cam.cfg["url"]).startswith("http"):
            self.cam.next_file()
        # 2) NHẬN DIỆN cả loạt ảnh rồi bỏ phiếu: biển đọc giống nhau ở nhiều ảnh, độ tin cậy cao thì thắng
        votes = defaultdict(float)
        best_img, best_score, per_frame = None, -1.0, []
        td = time.time()
        for img in shots:
            view, (ox, oy) = _crop_roi(img, roi)
            reads = model.recognize(view)
            if not reads:
                per_frame.append(None)
                best_img = best_img if best_img is not None else img
                continue
            plate, conf, box = reads[0]  # biển lớn nhất trong làn = xe đang ở cổng
            per_frame.append(f"{plate or '?'}:{conf:.2f}")
            score = conf * (1.0 if is_valid(plate) else 0.3)
            votes[plate] += score
            if score > best_score:
                best_score = score
                best_img = self._annotate(img, [box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy], plate)
        self._t["detect_ms"] = int((time.time() - td) * 1000)
        self._t["per_frame"] = per_frame   # vd ["51G12345:0.91", "51G12345:0.88", None] — xem ảnh nào hỏng
        if frames == 0:
            return self._done(gate, None, 0.0, None, f"Không lấy được ảnh: {self.cam.error}")
        image = self._save(gate, best_img)
        if not votes:
            return self._done(gate, None, 0.0, image, "Không thấy biển số trong ảnh")
        plate = max(votes, key=votes.get)
        conf = min(1.0, votes[plate] / frames)
        if not plate:
            return self._done(gate, None, 0.0, image, "Thấy biển nhưng không đọc được ký tự")
        if not is_valid(plate) or conf < config.PLATE_MIN_CONF:
            return self._done(gate, None, conf, image, f"Đọc chưa chắc chắn ({pretty(plate)}, {conf:.0%})",
                              guess=plate)
        return self._done(gate, plate, conf, image, "")

    def _done(self, gate, plate, conf, image, reason, guess=None):
        r = {"gate": gate, "plate": plate, "display": pretty(plate) if plate else None, "conf": round(conf, 3),
             "image": image, "reason": reason, "guess": guess, "ts": time.time()}
        self.recent = [r, *self.recent][:20]
        return r

    @staticmethod
    def _annotate(img, box, plate):
        img = img.copy()
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 220, 120), 2)
        cv2.putText(img, pretty(plate) or plate, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 220, 120), 2, cv2.LINE_AA)
        return img

    @staticmethod
    def _save(gate, img):
        if img is None:
            return None
        day = datetime.now().strftime("%Y%m%d")
        folder = config.PLATE_IMG_DIR / day
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{datetime.now().strftime('%H%M%S_%f')[:-3]}_{gate}.jpg"
        cv2.imwrite(str(folder / name), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return f"{day}/{name}"
