"""Nguồn video + nhận diện ô trống/có xe.

Ba bộ nhận diện:
  - classifier : mô hình phân loại từng ô tự huấn luyện (model_training/) — khuyến nghị
  - yolo       : YOLOv8 pretrained (COCO), ô có xe khi box xe phủ đủ tỉ lệ ROI
  - background : so sánh từng ROI với ảnh nền bãi trống (chạy tốt với xe mô hình / vật khối bất kỳ)
"""
import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from . import config
from .layout import Layout

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp"}


# ---------------------------------------------------------------- nguồn khung hình
class FrameSource:
    def __init__(self):
        self.source = None
        self.frame = None
        self.frame_ts = 0.0
        self.fps = 0.0
        self.error = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._gen = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def set_source(self, src):
        if src != self.source:
            self.source = src
            self._gen += 1
            self.frame = None
            self.error = ""

    def get(self):
        with self._lock:
            return (None if self.frame is None else self.frame.copy()), self.frame_ts

    def online(self):
        return self.frame is not None and time.time() - self.frame_ts < 5

    def _push(self, frame):
        now = time.time()
        with self._lock:
            if self.frame_ts:
                inst = 1.0 / max(now - self.frame_ts, 1e-3)
                self.fps = inst if self.fps == 0 else 0.9 * self.fps + 0.1 * inst
            self.frame, self.frame_ts = frame, now

    def _run(self):
        while not self._stop.is_set():
            src, gen = self.source, self._gen
            if not src or src == "none":
                time.sleep(0.3)
                continue
            try:
                if Path(src).suffix.lower() in IMAGE_EXT and Path(src).exists():
                    img = cv2.imread(src)
                    if img is None:
                        raise RuntimeError("không đọc được ảnh")
                    while gen == self._gen and not self._stop.is_set():
                        self._push(img.copy())
                        time.sleep(0.2)
                    continue
                # "0", "1"... = webcam gắn vào máy tính (kể cả điện thoại dùng DroidCam/Iriun qua USB)
                cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
                if not cap.isOpened():
                    raise RuntimeError("không mở được nguồn video")
                is_file = not src.isdigit() and Path(src).exists()
                self.error = ""
                while gen == self._gen and not self._stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        if is_file:  # lặp lại video
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        raise RuntimeError("mất luồng video")
                    self._push(frame)
                    if is_file:
                        time.sleep(1 / 25)
                cap.release()
            except Exception as e:
                self.error = str(e)
                time.sleep(2)


# ---------------------------------------------------------------- bộ nhận diện
class _RoiMixin:
    def __init__(self, layout: Layout):
        self.layout = layout
        self._masks = {}
        self._shape = None

    def _ensure_masks(self, frame):
        h, w = frame.shape[:2]
        if self._shape == (h, w):
            return
        sx, sy = w / self.layout.frame_w, h / self.layout.frame_h
        self._masks = {}
        for sid in self.layout.slot_ids:
            pts = np.array([[p[0] * sx, p[1] * sy] for p in self.layout.slots[sid]["roi"]], np.int32)
            m = np.zeros((h, w), np.uint8)
            cv2.fillPoly(m, [pts], 255)
            self._masks[sid] = m > 0
        self._shape = (h, w)


class BackgroundDetector(_RoiMixin):
    name = "background"

    def __init__(self, layout):
        super().__init__(layout)
        self.ref = None
        self.load_reference()

    @staticmethod
    def _prep(frame):
        return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)

    def load_reference(self):
        if config.REFERENCE_PATH.exists():
            img = cv2.imread(str(config.REFERENCE_PATH))
            self.ref = None if img is None else self._prep(img)

    def set_reference(self, frame):
        cv2.imwrite(str(config.REFERENCE_PATH), frame)
        self.ref = self._prep(frame)

    def detect(self, frame):
        if self.ref is None:
            return None, [], "Chưa có ảnh nền bãi trống — vào trang Thiết bị để chụp ảnh nền"
        self._ensure_masks(frame)
        g = self._prep(frame)
        ref = self.ref
        if ref.shape != g.shape:
            ref = cv2.resize(ref, (g.shape[1], g.shape[0]))
        diff = cv2.absdiff(g, ref) > config.BG_THRESHOLD
        occ = {sid: bool(diff[m].mean() > config.BG_RATIO) for sid, m in self._masks.items()}
        return occ, [], ""


class YoloDetector(_RoiMixin):
    name = "yolo"

    def __init__(self, layout, model_path=None):
        super().__init__(layout)
        from ultralytics import YOLO  # import trễ vì nặng
        self.model = YOLO(str(model_path or config.YOLO_MODEL))
        self.classes = config.YOLO_CLASSES or None

    def detect(self, frame):
        self._ensure_masks(frame)
        res = self.model.predict(frame, conf=config.YOLO_CONF, classes=self.classes,
                                 verbose=False, imgsz=640)[0]
        boxes = []
        h, w = frame.shape[:2]
        occ = {sid: False for sid in self._masks}
        for b in res.boxes:
            x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
            boxes.append((x1, y1, x2, y2, float(b.conf[0]), res.names[int(b.cls[0])]))
            bm = np.zeros((h, w), bool)
            bm[max(y1, 0):max(y2, 0), max(x1, 0):max(x2, 0)] = True
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            for sid, m in self._masks.items():
                inter = np.logical_and(bm, m).sum() / max(m.sum(), 1)
                inside = 0 <= cy < h and 0 <= cx < w and m[cy, cx]
                if inter >= config.YOLO_OVERLAP or inside:
                    occ[sid] = True
        return occ, boxes, ""


class ClassifierDetector:
    """Mô hình phân loại từng ô (huấn luyện trong model_training/, xuất ra pc_server/models/occupancy.pt).

    Cắt khung bao của từng ROI, phân loại cả 12 ô trong một batch.
    """
    name = "classifier"

    def __init__(self, layout, model_path=None, threshold=None):
        import torch
        self.torch = torch
        self.layout = layout
        model_path = Path(model_path or config.CLASSIFIER_MODEL)
        meta = json.loads(model_path.with_suffix(".json").read_text(encoding="utf-8"))
        self.size = meta["img_size"]
        self.mean = np.array(meta["mean"], np.float32).reshape(1, 1, 3)
        self.std = np.array(meta["std"], np.float32).reshape(1, 1, 3)
        # ngưỡng: chọn trên web > biến môi trường > ngưỡng lưu lúc huấn luyện
        self.default_threshold = float(meta.get("threshold", 0.5))
        self.threshold = float(threshold if threshold is not None
                               else os.getenv("CLASSIFIER_THRESHOLD", self.default_threshold))
        self.temperature = float(meta.get("temperature", 1.0))
        self.model = torch.jit.load(str(model_path), map_location="cpu").eval()
        self.probs = {}

    def _crops(self, frame):
        h, w = frame.shape[:2]
        sx, sy = w / self.layout.frame_w, h / self.layout.frame_h
        out = []
        for sid in self.layout.slot_ids:
            pts = np.array([[p[0] * sx, p[1] * sy] for p in self.layout.slots[sid]["roi"]], np.float32)
            x1, y1 = np.clip(pts.min(0).astype(int), 0, [w - 1, h - 1])
            x2, y2 = np.clip(pts.max(0).astype(int), 1, [w, h])
            crop = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
            crop = cv2.resize(crop, (self.size, self.size), interpolation=cv2.INTER_AREA)
            out.append(((crop.astype(np.float32) / 255.0) - self.mean) / self.std)
        return np.stack(out).transpose(0, 3, 1, 2)

    def detect(self, frame):
        x = self.torch.from_numpy(np.ascontiguousarray(self._crops(frame)))
        with self.torch.no_grad():
            logits = self.model(x)
        z = (logits[:, 1] - logits[:, 0]).numpy() / self.temperature
        p = 1 / (1 + np.exp(-z))
        self.probs = dict(zip(self.layout.slot_ids, p.round(3).tolist()))
        return {sid: bool(pi >= self.threshold) for sid, pi in self.probs.items()}, [], ""


# ---------------------------------------------------------------- chọn bộ nhận diện / mô hình
# Lựa chọn {"kind", "model", "threshold"} đặt trên web, lưu ở data/detector.json; chưa chọn thì theo biến môi trường.
# "model" là đường dẫn tương đối so với pc_server/ (vd. "models/occupancy.pt", "yolov8n.pt").
SELECTION_PATH = config.DATA_DIR / "detector.json"
KINDS = ("classifier", "yolo", "background", "none")


def _rel(path):
    path = Path(path)
    try:
        return path.resolve().relative_to(config.BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def model_path(model):
    p = Path(model)
    return p if p.is_absolute() else config.BASE_DIR / p


def default_selection():
    model = {"classifier": _rel(config.CLASSIFIER_MODEL), "yolo": config.YOLO_MODEL}.get(config.DETECTOR)
    return {"kind": config.DETECTOR, "model": model, "threshold": None}


def load_selection():
    if SELECTION_PATH.exists():
        try:
            sel = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
            if sel.get("kind") in KINDS:
                return {"kind": sel["kind"], "model": sel.get("model"), "threshold": sel.get("threshold")}
        except (ValueError, OSError):
            pass
    return default_selection()


def save_selection(sel):
    SELECTION_PATH.write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")


def list_models():
    """Các lựa chọn nhận diện: mô hình phân loại (file .pt kèm .json cùng tên trong models/),
    mô hình YOLO (các .pt còn lại trong pc_server/ và models/), so sánh ảnh nền."""
    out, seen = [], set()
    model_dir = config.CLASSIFIER_MODEL.parent
    for pt in sorted(model_dir.glob("*.pt")):
        try:
            meta = json.loads(pt.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "img_size" not in meta:
            continue
        seen.add(pt.resolve())
        out.append({"kind": "classifier", "model": _rel(pt), "name": pt.stem,
                    "size_mb": round(pt.stat().st_size / 1e6, 1),
                    "info": {k: meta.get(k) for k in ("arch", "dataset", "created", "threshold", "finetuned_on_custom",
                                                      "test_metrics", "unseen_camera_metrics")}})
    for d in (config.BASE_DIR, model_dir):
        for pt in sorted(d.glob("*.pt")):
            if pt.resolve() in seen:
                continue
            seen.add(pt.resolve())
            out.append({"kind": "yolo", "model": _rel(pt), "name": pt.stem,
                        "size_mb": round(pt.stat().st_size / 1e6, 1), "info": {}})
    if not any(m["kind"] == "yolo" for m in out):  # ultralytics tự tải về ở lần dùng đầu
        out.append({"kind": "yolo", "model": config.YOLO_MODEL, "name": Path(config.YOLO_MODEL).stem,
                    "size_mb": None, "info": {"download": True}})
    out.append({"kind": "background", "model": None, "name": "So sánh ảnh nền", "size_mb": None, "info": {}})
    return out


def make_detector(layout, sel=None):
    sel = sel or load_selection()
    kind = sel["kind"]
    if kind == "background":
        return BackgroundDetector(layout), ""
    if kind == "classifier":
        path = model_path(sel.get("model") or config.CLASSIFIER_MODEL)
        try:
            return ClassifierDetector(layout, path, sel.get("threshold")), ""
        except Exception as e:
            return None, (f"Không tải được mô hình phân loại {path.name} ({e}). "
                          f"Cần {path.name} và {path.with_suffix('.json').name} trong {path.parent}.")
    if kind == "yolo":
        model = sel.get("model") or config.YOLO_MODEL
        path = model_path(model)
        try:
            return YoloDetector(layout, path if path.exists() else model), ""
        except Exception as e:
            return None, f"Không tải được YOLO {model} ({e}). Chạy: pip install ultralytics"
    return None, ""


# ---------------------------------------------------------------- vòng lặp nhận diện
class DetectionEngine:
    def __init__(self, layout, state, source: FrameSource, made=None):
        """made: (bộ nhận diện, lỗi) tạo sẵn — để thử tải mô hình mới trước khi thay bộ đang chạy."""
        self.layout, self.state, self.source = layout, state, source
        self.detector, self.error = made or make_detector(layout)
        self.boxes = []
        self.raw = {}
        self.fps = 0.0
        self.last_ok = 0.0
        self._streak = {s: 0 for s in layout.slot_ids}
        self._stable = dict(state.detected)  # khởi tạo theo phiên còn mở trong DB
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self, wait=False):
        self._stop.set()
        if wait and self._thread.is_alive():
            self._thread.join(timeout=5)

    @property
    def name(self):
        return self.detector.name if self.detector else "none"

    def capture_reference(self):
        frame, _ = self.source.get()
        if frame is None:
            return False
        if not isinstance(self.detector, BackgroundDetector):
            cv2.imwrite(str(config.REFERENCE_PATH), frame)
            return True
        self.detector.set_reference(frame)
        return True

    def _run(self):
        last_ts = 0.0
        period = 1.0 / max(config.DETECT_FPS, 0.5)
        while not self._stop.is_set():
            t0 = time.time()
            frame, ts = self.source.get()
            if self.detector is None or frame is None or ts == last_ts or not self.source.online():
                time.sleep(0.2)
                continue
            last_ts = ts
            try:
                occ, boxes, err = self.detector.detect(frame)
                self.error = err
                if occ is not None:
                    self.boxes, self.raw = boxes, occ
                    self.last_ok = time.time()
                    self._smooth(occ)
            except Exception as e:
                self.error = f"Lỗi nhận diện: {e}"
            dt = time.time() - t0
            self.fps = 1.0 / max(dt, 1e-3) if dt > period else config.DETECT_FPS
            time.sleep(max(0.0, period - dt))

    def _smooth(self, occ):
        """Chỉ đổi trạng thái ô khi CONFIRM_FRAMES khung liên tiếp cho kết quả khác."""
        changed = {}
        for sid, v in occ.items():
            if v == self._stable[sid]:
                self._streak[sid] = 0
                continue
            self._streak[sid] += 1
            if self._streak[sid] >= config.CONFIRM_FRAMES:
                self._stable[sid] = v
                self._streak[sid] = 0
                changed[sid] = v
        if changed:
            self.state.set_detected(changed)


# ---------------------------------------------------------------- vẽ khung hình có chú thích
COLORS = {"free": (94, 197, 34), "occupied": (68, 68, 239), "reserved": (11, 158, 245)}  # BGR


def render_frame(frame, layout, statuses, boxes, detector_name):
    if frame is None:
        img = np.full((layout.frame_h, layout.frame_w, 3), 24, np.uint8)
        cv2.putText(img, "NO SIGNAL", (layout.frame_w // 2 - 90, layout.frame_h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 120, 120), 2, cv2.LINE_AA)
        return img
    out = frame.copy()
    h, w = out.shape[:2]
    sx, sy = w / layout.frame_w, h / layout.frame_h
    overlay = out.copy()
    for sid in layout.slot_ids:
        pts = np.array([[p[0] * sx, p[1] * sy] for p in layout.slots[sid]["roi"]], np.int32)
        col = COLORS.get(statuses.get(sid, "free"))
        cv2.fillPoly(overlay, [pts], col)
    out = cv2.addWeighted(overlay, 0.22, out, 0.78, 0)
    for sid in layout.slot_ids:
        pts = np.array([[p[0] * sx, p[1] * sy] for p in layout.slots[sid]["roi"]], np.int32)
        col = COLORS.get(statuses.get(sid, "free"))
        cv2.polylines(out, [pts], True, col, 2, cv2.LINE_AA)
        name = layout.label(sid)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].min()) + 22
        cv2.putText(out, name, (cx - 6 * len(name), cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    for (x1, y1, x2, y2, conf, name) in boxes:
        cv2.rectangle(out, (x1, y1), (x2, y2), (255, 200, 0), 2)
        cv2.putText(out, f"{name} {conf:.2f}", (x1, max(y1 - 5, 12)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (255, 200, 0), 1, cv2.LINE_AA)
    return out
