"""Khởi tạo linh kiện từ config.yaml. Mỗi linh kiện tạo độc lập để lỗi một chỗ không kéo theo chỗ khác.

Import thư viện phần cứng (gpiozero, luma, picamera2) bên trong từng hàm để chỉ nạp khi thật sự dùng.
"""
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path=None):
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_sensor(cfg, gate):
    """Cảm biến siêu âm HC-SR04 của cổng `in` / `out`."""
    from .ultrasonic import GateSensor
    g = cfg["gates"][gate]
    return GateSensor(g["trig"], g["echo"], g["trigger_cm"], cfg["gates"].get("sample_hz", 10), name=gate)


def make_barrier(cfg, gate):
    """Rào chắn servo SG90 của cổng `in` / `out`, góc đóng/mở riêng từng cổng."""
    from .barrier import ServoBarrier
    b = cfg["barrier"]
    return ServoBarrier(b[f"{gate}_pin"], b.get(f"{gate}_closed_angle", 0), b.get(f"{gate}_open_angle", 90))


def make_leds(cfg):
    from .leds import LedBank
    return LedBank(cfg["leds"]["pins"], cfg["leds"].get("active_high", True))


def make_tft(cfg):
    from .tft import Tft
    return Tft(**cfg["tft"])


def make_camera(cfg):
    from .camera import CameraStreamer
    c = cfg["camera"]
    return CameraStreamer(c["width"], c["height"], c["fps"], c["port"], c.get("hflip", False), c.get("vflip", False))
